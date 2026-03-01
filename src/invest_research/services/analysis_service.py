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
            return WeeklyAnalysis(
                framework_id=framework.id,
                week_start=week_start,
                week_end=week_end,
                news_analyses=[],
                weekly_summary="本周无相关新闻。",
            )

        # 构建历史摘要上下文
        historical_context = self._build_historical_context(framework.id)

        # 构建新闻列表（纯文本格式，避免 AI 输出时混淆引号）
        news_text_lines = []
        for i, article in enumerate(articles):
            date_str = article.published_at.strftime("%Y-%m-%d") if article.published_at else "未知"
            snippet = article.content_snippet[:100].replace("\n", " ")
            news_text_lines.append(
                f"[{i + 1}] {article.title} | 来源: {article.source} | 日期: {date_str}"
                f" | URL: {article.url} | 摘要: {snippet}"
            )
        news_text = "\n".join(news_text_lines)

        # 构建消息
        framework_context = (
            f"目标公司: {framework.company_name}\n"
            f"行业: {framework.industry} - {framework.sub_industry}\n"
            f"主营业务: {framework.business_description}\n"
            f"竞争对手: {', '.join(framework.competitors)}\n"
            f"宏观因素: {', '.join(framework.macro_factors)}\n"
        )

        financial_section = f"## 财务数据\n{financial_context}\n\n" if financial_context else ""

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 历史摘要\n{historical_context}\n\n"
            f"{financial_section}"
            f"## 本周新闻 ({len(articles)} 条)\n{news_text}\n\n"
            f"请对每条新闻进行分析，并生成周度总结。注意输出的 JSON 中所有字符串值内的双引号必须用反斜杠转义。"
        )

        messages = [{"role": "user", "content": user_message}]

        # 根据新闻条数动态计算 max_tokens，避免输出截断导致 JSON 解析失败
        estimated_tokens = 1024 + len(articles) * 300
        max_tokens = max(8192, min(estimated_tokens, 16384))

        response = self.claude.chat(
            messages=messages,
            prompt_name="news_analyst",
            model=self.settings.claude_model_light,
            max_tokens=max_tokens,
        )

        analysis = self._parse_analysis(response, framework.id, week_start, week_end)

        # 保存分析结果
        self.analysis_repo.save(analysis)
        logger.info(
            f"分析完成: {framework.company_name}，"
            f"分析了 {len(analysis.news_analyses)} 条新闻"
        )
        return analysis

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

            return WeeklyAnalysis(
                framework_id=framework_id,
                week_start=week_start,
                week_end=week_end,
                news_analyses=news_analyses,
                weekly_summary=data.get("weekly_summary", ""),
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
                return WeeklyAnalysis(
                    framework_id=framework_id,
                    week_start=week_start,
                    week_end=week_end,
                    news_analyses=news_analyses,
                    weekly_summary=data.get("weekly_summary", ""),
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
