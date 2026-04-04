import json
import logging
from datetime import datetime, timedelta

from invest_research.config import get_settings
from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.models import AnalysisFramework, WeeklyAnalysis, NewsAnalysisItem
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, claude_client: ClaudeClient, news_repo: NewsRepo, analysis_repo: AnalysisRepo):
        self.claude = claude_client
        self.news_repo = news_repo
        self.analysis_repo = analysis_repo
        self.settings = get_settings()

    def analyze_week(
        self,
        framework: AnalysisFramework,
        week_end: datetime | None = None,
        financial_context: str = "",
    ) -> WeeklyAnalysis:
        if week_end is None:
            week_end = datetime.now()

        # 增量: 非首次分析时从上次分析结束时间开始
        previous_analysis = self.analysis_repo.get_latest(framework.id)
        if previous_analysis:
            week_start = previous_analysis.week_end
        else:
            week_start = week_end - timedelta(days=7)

        # 获取本周新闻
        articles = self.news_repo.get_by_framework(
            framework.id, start_date=week_start, end_date=week_end
        )

        if not articles:
            logger.warning(f"框架 {framework.id} ({framework.company_name}) 本周无新闻")
            analysis = WeeklyAnalysis(
                framework_id=framework.id,
                week_start=week_start,
                week_end=week_end,
                news_analyses=[],
                weekly_summary="本周无相关新闻。",
            )
            self.analysis_repo.save(analysis)
            return analysis

        # 构建历史摘要上下文
        historical_context = self._build_historical_context(framework.id)

        # 构建框架上下文
        framework_context = (
            f"目标公司: {framework.company_name}\n"
            f"行业: {framework.industry} - {framework.sub_industry}\n"
            f"主营业务: {framework.business_description}\n"
            f"竞争对手: {', '.join(framework.competitors)}\n"
            f"宏观因素: {', '.join(framework.macro_factors)}\n"
        )
        if framework.analysis_dimensions:
            dims = framework.analysis_dimensions
            if "business_model" in dims:
                bm = dims["business_model"]
                framework_context += f"商业模式: {bm.get('moat_type', '')}，{bm.get('revenue_structure', '')}\n"
            if "financial_focus" in dims:
                ff = dims["financial_focus"]
                framework_context += f"财务关注: {', '.join(ff.get('key_metrics', []))}\n"
            if "risk_matrix" in dims:
                rm = dims["risk_matrix"]
                all_risks = []
                for cat in ("operational", "financial", "market", "regulatory"):
                    all_risks.extend(rm.get(cat, []))
                if all_risks:
                    framework_context += f"风险关注: {', '.join(all_risks[:6])}\n"
            if "strategy_specific" in dims:
                ss = dims["strategy_specific"]
                framework_context += "策略关注维度:\n"
                for k, v in ss.items():
                    framework_context += f"  - {k}: {v}\n"
        if framework.investment_strategy and framework.investment_strategy != "balanced":
            strategy_labels = {"high_dividend": "高分红稳定型", "high_growth": "高增长爆发型"}
            framework_context += f"投资策略: {strategy_labels.get(framework.investment_strategy, framework.investment_strategy)}\n"

        financial_section = f"## 财务数据\n{financial_context}\n\n" if financial_context else ""

        # 新闻过多时分批分析，避免输出超出 max_tokens 导致 JSON 截断
        batch_size = 20
        if len(articles) <= batch_size:
            analysis = self._call_analysis(
                articles, framework_context, historical_context, financial_section,
                framework.id, week_start, week_end,
            )
        else:
            logger.info(f"新闻 {len(articles)} 条，分批分析（每批 {batch_size} 条）")
            all_news_analyses = []
            for i in range(0, len(articles), batch_size):
                batch = articles[i:i + batch_size]
                batch_label = f"第 {i // batch_size + 1} 批（{len(batch)} 条）"
                logger.info(f"分析 {batch_label}")
                batch_result = self._call_analysis(
                    batch, framework_context, historical_context, financial_section,
                    framework.id, week_start, week_end,
                )
                all_news_analyses.extend(batch_result.news_analyses)

            # 合并后生成总结
            raw_summary = self._generate_summary(
                framework_context, all_news_analyses, historical_context
            )
            signal, confidence = self._extract_signal_from_summary(raw_summary)
            weekly_summary = self._format_weekly_summary(raw_summary)
            analysis = WeeklyAnalysis(
                framework_id=framework.id,
                week_start=week_start,
                week_end=week_end,
                news_analyses=all_news_analyses,
                weekly_summary=weekly_summary,
                signal=signal,
                confidence=confidence,
            )

        # 保存分析结果
        self.analysis_repo.save(analysis)
        logger.info(
            f"分析完成: {framework.company_name}，"
            f"分析了 {len(analysis.news_analyses)} 条新闻"
        )
        return analysis

    def _call_analysis(
        self,
        articles,
        framework_context: str,
        historical_context: str,
        financial_section: str,
        framework_id: int,
        week_start: datetime,
        week_end: datetime,
    ) -> WeeklyAnalysis:
        """对一批新闻调用 AI 分析。"""
        news_text_lines = []
        for i, article in enumerate(articles):
            date_str = article.published_at.strftime("%Y-%m-%d") if article.published_at else "未知"
            snippet = article.content_snippet[:100].replace("\n", " ")
            news_text_lines.append(
                f"[{i + 1}] {article.title} | 来源: {article.source} | 日期: {date_str}"
                f" | URL: {article.url} | 摘要: {snippet}"
            )
        news_text = "\n".join(news_text_lines)

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 历史摘要\n{historical_context}\n\n"
            f"{financial_section}"
            f"## 本周新闻 ({len(articles)} 条)\n{news_text}\n\n"
            f"请对每条新闻进行分析，并生成周度总结。注意输出的 JSON 中所有字符串值内的双引号必须用反斜杠转义。"
        )

        messages = [{"role": "user", "content": user_message}]

        response = self.claude.chat(
            messages=messages,
            prompt_name="news_analyst",
            model=self.settings.claude_model_light,
            max_tokens=8192,
        )

        return self._parse_analysis(response, framework_id, week_start, week_end)

    def _generate_summary(
        self,
        framework_context: str,
        all_news_analyses: list[NewsAnalysisItem],
        historical_context: str,
    ) -> str:
        """基于所有批次分析结果生成总结。"""
        analyses_text = "\n".join(
            f"- [{item.sentiment}] [{item.category}] [{item.impact}] {item.title}: {item.summary}"
            for item in all_news_analyses
        )
        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 历史摘要\n{historical_context}\n\n"
            f"## 本周新闻分析结果 ({len(all_news_analyses)} 条)\n{analyses_text}\n\n"
            f"请基于以上所有新闻分析，生成结构化的周度总结，严格按以下 JSON 格式输出：\n"
            f'{{"key_events": ["事件1：描述+影响", "事件2"], "overall_impact": "综合影响判断（100字以内）", "watch_signals": ["关注信号1"], "signal": "bullish/bearish/neutral", "confidence": 0.7}}\n'
            f"key_events 最多 3 个，watch_signals 最多 3 条。signal 取值 bullish/bearish/neutral，confidence 取值 0.0~1.0。只输出 JSON，不要其他文字。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            model=self.settings.claude_model_light,
            max_tokens=1024,
        )
        # 尝试解析结构化输出
        try:
            json_str = ClaudeClient._extract_json(response)
            data = json.loads(json_str)
            return data  # 返回原始 dict，由调用方处理
        except Exception:
            # 回退：直接用原始文本
            return response.strip()

    def _build_historical_context(self, framework_id: int) -> str:
        recent = self.analysis_repo.get_recent(
            framework_id, weeks=self.settings.analysis_rolling_weeks
        )
        if not recent:
            return "无历史分析记录。"

        summaries = []
        for analysis in reversed(recent):
            week_label = analysis.week_end.strftime("%Y-%m-%d")
            summaries.append(f"[{week_label}] {analysis.weekly_summary}")

        return "\n".join(summaries)

    @staticmethod
    def _parse_analysis(
        response: str,
        framework_id: int,
        week_start: datetime,
        week_end: datetime,
    ) -> WeeklyAnalysis:
        try:
            json_str = ClaudeClient._extract_json(response)
            data = json.loads(json_str)

            news_analyses = [
                NewsAnalysisItem(**item) for item in data.get("news_analyses", [])
            ]

            raw_summary = data.get("weekly_summary", "")
            signal, confidence = AnalysisService._extract_signal_from_summary(raw_summary)
            weekly_summary = AnalysisService._format_weekly_summary(raw_summary)
            return WeeklyAnalysis(
                framework_id=framework_id,
                week_start=week_start,
                week_end=week_end,
                news_analyses=news_analyses,
                weekly_summary=weekly_summary,
                signal=signal,
                confidence=confidence,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"JSON 解析失败，尝试修复: {e}")
            # 尝试修复截断的 JSON
            json_str = ClaudeClient._extract_json(response)
            repaired = AnalysisService._repair_json(json_str)
            try:
                data = json.loads(repaired)
                news_analyses = [
                    NewsAnalysisItem(**item) for item in data.get("news_analyses", [])
                ]
                raw_summary = data.get("weekly_summary", "")
                signal, confidence = AnalysisService._extract_signal_from_summary(raw_summary)
                weekly_summary = AnalysisService._format_weekly_summary(raw_summary)
                return WeeklyAnalysis(
                    framework_id=framework_id,
                    week_start=week_start,
                    week_end=week_end,
                    news_analyses=news_analyses,
                    weekly_summary=weekly_summary,
                    signal=signal,
                    confidence=confidence,
                )
            except Exception:
                logger.error(f"JSON 修复失败，返回空分析")
                return WeeklyAnalysis(
                    framework_id=framework_id,
                    week_start=week_start,
                    week_end=week_end,
                    news_analyses=[],
                    weekly_summary=f"分析结果解析失败",
                )

    @staticmethod
    def _format_weekly_summary(raw) -> str:
        """将结构化 weekly_summary 转为可读文本，兼容旧版纯字符串格式。"""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            parts = []
            key_events = raw.get("key_events", [])
            if key_events:
                events_text = "；".join(key_events[:3])
                parts.append(f"【关键事件】{events_text}")
            overall = raw.get("overall_impact", "")
            if overall:
                parts.append(f"【综合影响】{overall}")
            signals = raw.get("watch_signals", [])
            if signals:
                signals_text = "；".join(signals[:3])
                parts.append(f"【关注信号】{signals_text}")
            # 标准化信号
            signal = raw.get("signal", "")
            confidence = raw.get("confidence", 0.0)
            if signal:
                parts.append(f"【信号】signal: {signal}, confidence: {confidence}")
            return " ".join(parts) if parts else "无总结"
        return str(raw)

    @staticmethod
    def _extract_signal_from_summary(raw) -> tuple[str, float]:
        """从 weekly_summary 原始 dict 中提取标准化信号。"""
        if isinstance(raw, dict):
            signal = raw.get("signal", "neutral")
            confidence = raw.get("confidence", 0.0)
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = 0.0
            if signal not in ("bullish", "bearish", "neutral"):
                signal = "neutral"
            return signal, min(max(confidence, 0.0), 1.0)
        return "neutral", 0.0

    @staticmethod
    def _repair_json(text: str) -> str:
        """尝试修复截断或格式错误的 JSON。"""
        # 平衡括号
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")

        # 如果在字符串中间截断，先关闭字符串
        if text.rstrip().endswith(("\\", ",")):
            text = text.rstrip().rstrip(",").rstrip("\\")

        # 尝试关闭未完成的字符串
        quote_count = text.count('"') - text.count('\\"')
        if quote_count % 2 != 0:
            text += '"'

        text += "]" * max(0, open_brackets)
        text += "}" * max(0, open_braces)
        return text
