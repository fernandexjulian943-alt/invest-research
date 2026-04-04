"""按需数据拉取调度器：根据 Pass 1 分析结果，调用对应 Service 拉取数据。

拉取的数据同时写入长期记忆（framework 表），下次对话不用重复拉取。
"""

import json
import logging
from datetime import datetime

from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.data.reflection_repo import ReflectionRepo
from invest_research.models import AnalysisFramework, InvestmentReport
from invest_research.services.stock_quote_service import StockQuoteService
from invest_research.services.financial_service import FinancialDataService
from invest_research.services.dividend_service import DividendService
from invest_research.services.market_scanner_service import MarketScannerService

logger = logging.getLogger(__name__)

# 数据类型 → 中文描述（前端展示用）
DATA_TYPE_NAMES = {
    "realtime_quote": "实时行情",
    "financial_summary": "财报数据",
    "dividend_history": "分红历史",
    "technical_detail": "技术面分析",
    "xueqiu_sentiment": "雪球情绪",
    "news_analysis": "新闻分析",
    "debate_detail": "多空辩论",
    "reflection_memories": "历史教训",
    "market_screening": "市场筛选",
}


class DataFetcher:
    """按需拉取数据，结果写入长期记忆。"""

    def __init__(self):
        self._quote_service = StockQuoteService()
        self._financial_service = FinancialDataService()
        self._dividend_service = DividendService()
        self._scanner_service = MarketScannerService()

    def fetch_one(self, key: str, framework: AnalysisFramework | None,
                  report: InvestmentReport | None = None,
                  user_message: str = "") -> tuple[str, str]:
        """拉取单个数据类型，返回 (key, 格式化文本)。失败返回空字符串。

        Args:
            framework: 分析框架（市场级筛选时为 None）
            user_message: 用户消息（market_screening 需要从中提取条件）
        """
        try:
            handler = getattr(self, f"_fetch_{key}", None)
            if not handler:
                logger.warning(f"未知数据类型: {key}")
                return key, ""
            # market_screening 不需要 framework，需要 user_message
            if key == "market_screening":
                text = handler(framework, report, user_message)
            else:
                text = handler(framework, report)
            return key, text
        except Exception as e:
            code = framework.stock_code if framework else "MARKET"
            logger.error(f"拉取 {key} 失败 [{code}]: {e}")
            return key, ""

    def fetch_batch(self, keys: list[str], framework: AnalysisFramework,
                    report: InvestmentReport | None = None,
                    callback=None) -> dict[str, str]:
        """批量拉取，逐个完成时调用 callback(key)。返回 {key: text}。"""
        results = {}
        for key in keys:
            _, text = self.fetch_one(key, framework, report)
            results[key] = text
            if callback:
                callback(key)
        return results

    # === 各数据类型拉取 ===

    def _fetch_realtime_quote(self, fw: AnalysisFramework, _report) -> str:
        quote = self._quote_service.fetch_quote(fw.stock_code)
        if quote.get("error"):
            return ""
        lines = ["## 实时行情数据"]
        if quote.get("name"):
            lines.append(f"- 名称: {quote['name']}")
        if quote.get("price") is not None:
            lines.append(f"- 现价: {quote['price']} {quote.get('currency', '')}")
        if quote.get("change_pct") is not None:
            lines.append(f"- 涨跌幅: {quote['change_pct']:.2f}%")
        if quote.get("pe_ttm") is not None:
            lines.append(f"- 市盈率(TTM): {quote['pe_ttm']:.2f}")
        if quote.get("pb") is not None:
            lines.append(f"- 市净率: {quote['pb']:.2f}")
        if quote.get("market_cap") is not None:
            cap = quote["market_cap"]
            if cap >= 1e12:
                lines.append(f"- 总市值: {cap/1e12:.2f}万亿")
            elif cap >= 1e8:
                lines.append(f"- 总市值: {cap/1e8:.2f}亿")
            else:
                lines.append(f"- 总市值: {cap:,.0f}")
        if quote.get("dividend_yield") is not None:
            lines.append(f"- 股息率(TTM): {quote['dividend_yield']:.2f}%")
        if quote.get("week52_high") is not None:
            lines.append(f"- 52周最高: {quote['week52_high']}")
        if quote.get("week52_low") is not None:
            lines.append(f"- 52周最低: {quote['week52_low']}")
        if quote.get("timestamp"):
            lines.append(f"- 数据时间: {quote['timestamp']}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _fetch_financial_summary(self, fw: AnalysisFramework, _report) -> str:
        summary = self._financial_service.fetch_summary(fw.stock_code)
        if not summary:
            return ""
        # 写入长期记忆
        try:
            conn = init_db()
            try:
                FrameworkRepo(conn).save_financial_cache(fw.id, summary)
            finally:
                conn.close()
            logger.info(f"财报数据已写入长期记忆 [{fw.stock_code}]")
        except Exception as e:
            logger.warning(f"写入财报缓存失败: {e}")
        return f"## 最新财务数据\n{summary}"

    def _fetch_dividend_history(self, fw: AnalysisFramework, _report) -> str:
        result = self._dividend_service.fetch_dividend(fw.stock_code)
        if result.get("error"):
            return ""
        dividends = result.get("dividends", [])
        summary = result.get("summary", {})
        yield_trend = result.get("yield_trend", [])
        if not dividends:
            return ""

        lines = ["## 分红历史数据"]
        if summary.get("total_count"):
            lines.append(f"- 累计分红次数: {summary['total_count']}次")
        if summary.get("total_cash_per_share"):
            lines.append(f"- 累计每股现金分红: {summary['total_cash_per_share']:.4f}元")
        if summary.get("avg_annual_cash"):
            lines.append(f"- 年均每股分红: {summary['avg_annual_cash']:.4f}元")

        if yield_trend:
            lines.append("\n### 各年度每股分红")
            for item in yield_trend[:5]:
                lines.append(f"- {item['year']}年: {item['cash_per_share']:.4f}元/股")

        lines.append("\n### 最近分红明细")
        for d in dividends[:3]:
            parts = []
            if d.get("announce_date"):
                parts.append(f"公告日: {d['announce_date']}")
            if d.get("cash_per_share"):
                parts.append(f"派息: {d['cash_per_share']}元/股")
            if d.get("ex_date"):
                parts.append(f"除权日: {d['ex_date']}")
            if parts:
                lines.append(f"- {' | '.join(parts)}")
        return "\n".join(lines)

    def _fetch_technical_detail(self, _fw: AnalysisFramework, report: InvestmentReport | None) -> str:
        """技术面从已有报告中提取（不重新计算，成本太高）。"""
        if not report or not report.technical_detail:
            return ""
        detail = report.technical_detail
        if isinstance(detail, dict):
            lines = ["## 技术面分析"]
            if "trend" in detail:
                lines.append(f"- 趋势: {detail.get('trend', '')} (强度: {detail.get('trend_strength', '')})")
            if "key_levels" in detail:
                levels = detail["key_levels"]
                if levels.get("support"):
                    lines.append(f"- 支撑位: {levels['support']}")
                if levels.get("resistance"):
                    lines.append(f"- 阻力位: {levels['resistance']}")
            if "indicators" in detail:
                lines.append(f"- 指标: {json.dumps(detail['indicators'], ensure_ascii=False)}")
            return "\n".join(lines)
        return f"## 技术面分析\n{detail}"

    def _fetch_xueqiu_sentiment(self, _fw: AnalysisFramework, report: InvestmentReport | None) -> str:
        if not report or not report.xueqiu_detail:
            return ""
        return f"## 雪球情绪分析\n{report.xueqiu_detail}"

    def _fetch_news_analysis(self, _fw: AnalysisFramework, report: InvestmentReport | None) -> str:
        if not report or not report.news_detail:
            return ""
        return f"## 新闻情绪分析\n{report.news_detail}"

    def _fetch_debate_detail(self, _fw: AnalysisFramework, report: InvestmentReport | None) -> str:
        if not report or not report.debate_detail:
            return ""
        detail = report.debate_detail
        if isinstance(detail, dict):
            parts = []
            if "bull" in detail:
                bull = detail["bull"]
                parts.append("## 看多论述")
                if isinstance(bull, dict):
                    parts.append(f"**论点**: {bull.get('thesis', '')}")
                    for ev in (bull.get("supporting_evidence") or [])[:5]:
                        parts.append(f"- {ev}")
            if "bear" in detail:
                bear = detail["bear"]
                parts.append("\n## 看空论述")
                if isinstance(bear, dict):
                    parts.append(f"**论点**: {bear.get('thesis', '')}")
                    for rf in (bear.get("risk_factors") or [])[:5]:
                        parts.append(f"- {rf}")
            return "\n".join(parts)
        return f"## 多空辩论\n{detail}"

    def _fetch_reflection_memories(self, fw: AnalysisFramework, _report) -> str:
        try:
            conn = init_db()
            try:
                repo = ReflectionRepo(conn)
                parts = []
                for role_key in ["bull", "bear", "risk_advisor", "financial", "news"]:
                    memories = repo.get_by_framework_and_role(fw.id, role_key, limit=2)
                    if memories:
                        parts.append(f"## {role_key} 历史教训")
                        for m in memories:
                            parts.append(f"- {m.reflection[:150]}")
                return "\n".join(parts)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"加载反思记忆失败: {e}")
            return ""

    def _fetch_market_screening(self, _fw, _report, user_message: str = "") -> str:
        """全市场筛选：从用户消息提取条件，执行筛选，返回格式化结果。"""
        if not user_message:
            return ""

        criteria = self._extract_screening_criteria(user_message)
        logger.info(f"筛选条件: {criteria}")

        scan_type = criteria.get("type", "pe")
        sort_dir = criteria.get("sort", "asc")
        limit = min(criteria.get("limit", 30), 50)
        filters = criteria.get("filters", {})

        try:
            if scan_type == "industry" and filters.get("industry"):
                results = self._scanner_service.scan_by_industry(
                    filters["industry"], limit=limit,
                )
            elif scan_type == "pb":
                results = self._scanner_service.scan_by_pb(
                    sort=sort_dir, limit=limit,
                    pb_min=filters.get("pb_min"),
                    pb_max=filters.get("pb_max"),
                    percentile_min=filters.get("percentile_min"),
                    percentile_max=filters.get("percentile_max"),
                )
            elif scan_type == "mixed":
                # 混合：先 PE 筛再 PB 筛（简单实现）
                results = self._scanner_service.scan_by_pe(
                    sort=sort_dir, limit=limit * 3,  # 多取一些再二次过滤
                    percentile_min=filters.get("percentile_min"),
                    percentile_max=filters.get("percentile_max"),
                )
                # 如果有 PB 条件，二次过滤
                if filters.get("pb_max") or filters.get("pb_min"):
                    pb_results = self._scanner_service.scan_by_pb(
                        sort=sort_dir, limit=5000,
                        pb_min=filters.get("pb_min"),
                        pb_max=filters.get("pb_max"),
                    )
                    pb_codes = {item["code"] for item in pb_results["items"]}
                    results["items"] = [
                        item for item in results["items"] if item["code"] in pb_codes
                    ][:limit]
                    results["count"] = len(results["items"])
                if filters.get("pe_max") or filters.get("pe_min"):
                    items = results["items"]
                    if filters.get("pe_max"):
                        items = [i for i in items if i.get("pe") and i["pe"] <= filters["pe_max"]]
                    if filters.get("pe_min"):
                        items = [i for i in items if i.get("pe") and i["pe"] >= filters["pe_min"]]
                    results["items"] = items[:limit]
                    results["count"] = len(results["items"])
            else:
                # 默认 PE
                results = self._scanner_service.scan_by_pe(
                    sort=sort_dir, limit=limit,
                    percentile_min=filters.get("percentile_min"),
                    percentile_max=filters.get("percentile_max"),
                )
                # 如果有 PE 绝对值过滤
                if filters.get("pe_max") or filters.get("pe_min"):
                    items = results["items"]
                    if filters.get("pe_max"):
                        items = [i for i in items if i.get("pe") and i["pe"] <= filters["pe_max"]]
                    if filters.get("pe_min"):
                        items = [i for i in items if i.get("pe") and i["pe"] >= filters["pe_min"]]
                    results["items"] = items[:limit]
                    results["count"] = len(results["items"])

            return self._scanner_service.format_results_text(results)

        except Exception as e:
            logger.error(f"市场筛选执行失败: {e}")
            return f"## 市场筛选结果\n\n筛选执行失败: {str(e)[:100]}"

    def _extract_screening_criteria(self, user_message: str) -> dict:
        """从用户消息提取筛选条件（LLM 解析）。"""
        try:
            from invest_research.config import get_settings
            from invest_research.services.claude_client import ClaudeClient
            settings = get_settings()
            client = ClaudeClient(settings)

            prompt_template = client._load_prompt("screening_criteria")
            prompt = prompt_template.replace("{{user_message}}", user_message)

            result = client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            json_str = client._extract_json(result)
            parsed = json.loads(json_str)
            # 基本校验
            if parsed.get("type") not in ("pe", "pb", "industry", "mixed"):
                parsed["type"] = "pe"
            parsed["limit"] = min(parsed.get("limit", 30), 50)
            return parsed
        except Exception as e:
            logger.warning(f"筛选条件提取失败: {e}，使用默认 PE 排序")
            return {"type": "pe", "sort": "asc", "limit": 30, "filters": {}}
