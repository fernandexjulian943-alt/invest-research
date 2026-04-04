"""上下文组装器：按角色从本地数据库拉取相关数据，组装为 LLM 上下文。"""

import json
import logging
from datetime import datetime, timedelta

from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.data.reflection_repo import ReflectionRepo
from invest_research.models import AnalysisFramework, InvestmentReport
from invest_research.services.stock_quote_service import StockQuoteService
from invest_research.services.financial_service import FinancialDataService
from invest_research.services.dividend_service import DividendService

logger = logging.getLogger(__name__)

# 数据新鲜度阈值（天）
REPORT_STALE_DAYS = 7
FINANCIAL_STALE_DAYS = 30


class DataContext:
    """组装后的上下文数据。"""

    def __init__(self):
        self.framework: AnalysisFramework | None = None
        self.latest_report: InvestmentReport | None = None
        self.context_text: str = ""
        self.data_refs: list[str] = []  # 引用的数据标识
        self.stale_warnings: list[dict] = []  # 过时数据警告


class ContextAssembler:
    def __init__(self):
        self._quote_service = StockQuoteService()
        self._financial_service = FinancialDataService()
        self._dividend_service = DividendService()

    def build_market_inventory(self) -> dict:
        """构建市场级数据目录（无 framework，只有筛选类数据）。"""
        return {
            "available": {},
            "missing": {"market_screening": "全市场筛选结果（PE/PB/行业等）"},
            "framework": None,
            "report": None,
        }

    def assemble_market_context(self, extra_data: dict[str, str]) -> "DataContext":
        """市场级上下文组装（无 framework）。"""
        ctx = DataContext()
        parts = ["## 全市场分析模式\n\n当前为全市场对话，可基于筛选结果进行分析。"]
        if extra_data:
            for key, text in extra_data.items():
                if text:
                    parts.append(text)
                    ctx.data_refs.append(f"fetched_{key}")
        ctx.context_text = "\n\n".join(parts)
        return ctx

    def build_data_inventory(self, framework_id: int) -> dict:
        """构建数据目录：当前有什么、缺什么、新鲜度如何。

        Returns:
            {
                "available": {"key": "描述（含新鲜度）", ...},
                "missing": {"key": "描述", ...},
                "framework": AnalysisFramework,
                "report": InvestmentReport | None,
            }
        """
        conn = init_db()
        try:
            fw_repo = FrameworkRepo(conn)
            report_repo = ReportRepo(conn)

            fw = fw_repo.get_by_id(framework_id)
            if not fw:
                return {"available": {}, "missing": {}, "framework": None, "report": None}

            report = report_repo.get_latest(framework_id)
            now = datetime.now()
            available = {}
            missing = {}

            # 实时行情（总是需要重新获取，列为 missing）
            missing["realtime_quote"] = "实时行情（价格/PE/PB/市值/股息率）"

            # 财报数据
            if fw.financial_summary:
                age = ""
                if fw.financial_fetched_at:
                    fetched = fw.financial_fetched_at
                    if isinstance(fetched, str):
                        fetched = datetime.fromisoformat(fetched)
                    days = (now - fetched).days
                    age = f"，{days}天前获取"
                    if days > FINANCIAL_STALE_DAYS:
                        age += "（已过期）"
                        missing["financial_summary"] = f"财报数据{age}，建议刷新"
                        # 同时也列为 available（过期但可用）
                available["financial_summary"] = f"财报摘要（营收/利润/ROE 等{age}）"
            else:
                missing["financial_summary"] = "财报数据（未获取）"

            # 分红历史（不存 DB，总是列为 missing）
            missing["dividend_history"] = "分红历史（年度派息/趋势）"

            # 以下数据来源于最新报告
            if report:
                report_age = (now - report.report_date).days if report.report_date else 999
                age_note = f"，{report_age}天前" if report.report_date else ""

                if report.technical_detail:
                    available["technical_detail"] = f"技术面分析（趋势/支撑阻力/指标{age_note}）"
                else:
                    missing["technical_detail"] = "技术面分析（无数据）"

                if report.xueqiu_detail:
                    available["xueqiu_sentiment"] = f"雪球情绪分析{age_note}"
                else:
                    missing["xueqiu_sentiment"] = "雪球情绪分析（无数据）"

                if report.news_detail:
                    available["news_analysis"] = f"新闻情绪分析{age_note}"
                else:
                    missing["news_analysis"] = "新闻分析（无数据）"

                if report.debate_detail:
                    available["debate_detail"] = f"多空辩论{age_note}"
                else:
                    missing["debate_detail"] = "多空辩论（无数据）"

                # 报告概览
                available["latest_report"] = f"投研报告（评级: {report.investment_rating}{age_note}）"
            else:
                missing["technical_detail"] = "技术面分析（无报告）"
                missing["xueqiu_sentiment"] = "雪球情绪分析（无报告）"
                missing["news_analysis"] = "新闻分析（无报告）"
                missing["debate_detail"] = "多空辩论（无报告）"

            # 反思记忆
            try:
                reflection_repo = ReflectionRepo(conn)
                has_reflections = bool(reflection_repo.get_by_framework_and_role(fw.id, "risk_advisor", limit=1))
                if has_reflections:
                    available["reflection_memories"] = "历史教训（反思记忆）"
                else:
                    missing["reflection_memories"] = "历史教训（无反思记录）"
            except Exception:
                missing["reflection_memories"] = "历史教训（查询失败）"

            return {
                "available": available,
                "missing": missing,
                "framework": fw,
                "report": report,
            }
        finally:
            conn.close()

    def assemble_with_extra(self, framework_id: int, role: str,
                            extra_data: dict[str, str]) -> DataContext:
        """在标准组装基础上，合并额外拉取的数据。"""
        ctx = self.assemble(framework_id, role)
        if extra_data:
            extra_parts = []
            for key, text in extra_data.items():
                if text:
                    extra_parts.append(text)
                    ctx.data_refs.append(f"fetched_{key}")
            if extra_parts:
                ctx.context_text += "\n\n" + "\n\n".join(extra_parts)
        return ctx

    def assemble(self, framework_id: int, role: str) -> DataContext:
        """根据角色组装对应的本地数据上下文。"""
        ctx = DataContext()
        conn = init_db()
        try:
            fw_repo = FrameworkRepo(conn)
            report_repo = ReportRepo(conn)
            reflection_repo = ReflectionRepo(conn)

            ctx.framework = fw_repo.get_by_id(framework_id)
            if not ctx.framework:
                ctx.context_text = "未找到该股票的分析框架。"
                return ctx

            ctx.latest_report = report_repo.get_latest(framework_id)
            now = datetime.now()

            # 基础信息（所有角色共用）
            base_info = self._build_base_info(ctx.framework, ctx.latest_report, now)

            # 实时行情（所有角色共用）
            quote_text = self._fetch_realtime_quote(ctx.framework.stock_code)
            if quote_text:
                base_info += f"\n\n{quote_text}"
                ctx.data_refs.append("realtime_quote")

            # 按角色组装专属上下文
            if role == "financial":
                ctx.context_text = self._assemble_financial(ctx, base_info, now)
            elif role == "quant":
                ctx.context_text = self._assemble_quant(ctx, base_info, now)
            elif role == "sentiment":
                ctx.context_text = self._assemble_sentiment(ctx, base_info, now)
            elif role == "debate":
                ctx.context_text = self._assemble_debate(ctx, base_info, reflection_repo, now)
            elif role == "competitor":
                ctx.context_text = self._assemble_competitor(ctx, base_info)
            else:
                # general: 概览
                ctx.context_text = self._assemble_general(ctx, base_info, now)

        finally:
            conn.close()

        return ctx

    def _build_base_info(
        self, fw: AnalysisFramework, report: InvestmentReport | None, now: datetime
    ) -> str:
        """构建基础公司信息。"""
        lines = [
            f"## 公司概况",
            f"- 公司: {fw.company_name} ({fw.stock_code})",
            f"- 行业: {fw.industry} / {fw.sub_industry}",
            f"- 业务: {fw.business_description[:200]}" if fw.business_description else "",
            f"- 投资策略: {fw.investment_strategy or '均衡'}",
        ]

        if report:
            report_age = (now - report.report_date).days if report.report_date else 999
            lines.append(f"\n## 最新报告概况 (报告日期: {report.report_date.strftime('%Y-%m-%d') if report.report_date else '未知'}, {report_age}天前)")
            lines.append(f"- 投资评级: {report.investment_rating}")
            if report.signal_summary:
                ss = report.signal_summary
                lines.append(f"- 综合信号: {ss.overall_signal} (置信度: {ss.overall_confidence})")
                lines.append(f"- 信号一致性: {ss.consistency}")
                if ss.conflicts:
                    lines.append(f"- 信号冲突: {ss.conflicts}")

        return "\n".join(line for line in lines if line)

    def _assemble_general(self, ctx: DataContext, base_info: str, now: datetime) -> str:
        """综合顾问：概览 + 评级 + 摘要 + 关键风险/机会。"""
        parts = [base_info]
        ctx.data_refs.append("base_info")

        # 分红历史（综合顾问也需要）
        dividend_text = self._fetch_dividend_history(ctx.framework.stock_code)
        if dividend_text:
            ctx.data_refs.append("dividend_history")
            parts.append(dividend_text)

        report = ctx.latest_report
        if report:
            ctx.data_refs.append(f"report_{report.id}")
            self._check_report_staleness(ctx, report, now)

            if report.executive_summary:
                parts.append(f"\n## 执行摘要\n{report.executive_summary}")

            if report.rating_rationale:
                parts.append(f"\n## 评级理由\n{report.rating_rationale}")

            if report.risks:
                parts.append("\n## 主要风险")
                for r in report.risks[:3]:
                    parts.append(f"- [{r.severity}] {r.description}")

            if report.opportunities:
                parts.append("\n## 主要机会")
                for o in report.opportunities[:3]:
                    parts.append(f"- [{o.confidence}] {o.description}")

            if report.rating_change_reason:
                parts.append(f"\n## 评级变动\n{report.rating_change_reason}")
        else:
            parts.append("\n**暂无投研报告。** 建议先生成一份完整报告再进行深入对话。")

        return "\n".join(parts)

    def _assemble_financial(self, ctx: DataContext, base_info: str, now: datetime) -> str:
        """财务分析师：财务数据 + 财务分析详情。"""
        parts = [base_info]
        ctx.data_refs.append("base_info")

        fw = ctx.framework
        report = ctx.latest_report

        # 财务数据：优先用缓存，过期或缺失则实时获取
        has_financial = bool(fw.financial_summary)
        is_stale = False
        if has_financial and fw.financial_fetched_at:
            fetched = fw.financial_fetched_at
            if isinstance(fetched, str):
                fetched = datetime.fromisoformat(fetched)
            is_stale = (now - fetched).days > FINANCIAL_STALE_DAYS

        if has_financial and not is_stale:
            ctx.data_refs.append("financial_summary")
            parts.append(f"\n## 财务数据\n{fw.financial_summary}")
        else:
            # 缓存缺失或过期，实时获取
            live_data = self._fetch_live_financial(fw.stock_code)
            if live_data:
                ctx.data_refs.append("financial_live")
                parts.append(f"\n## 最新财务数据（实时获取）\n{live_data}")
            elif has_financial:
                # 实时获取失败，退回使用过期缓存
                ctx.data_refs.append("financial_summary")
                self._check_financial_staleness(ctx, fw, now)
                parts.append(f"\n## 财务数据\n{fw.financial_summary}")

        # 分红历史数据
        dividend_text = self._fetch_dividend_history(fw.stock_code)
        if dividend_text:
            ctx.data_refs.append("dividend_history")
            parts.append(dividend_text)

        if report:
            ctx.data_refs.append(f"report_{report.id}")
            self._check_report_staleness(ctx, report, now)

            if report.financial_detail:
                ctx.data_refs.append("financial_detail")
                parts.append(f"\n## AI 财务分析\n{report.financial_detail}")

            # 信号
            if report.analyst_signals and report.analyst_signals.financial:
                sig = report.analyst_signals.financial
                parts.append(f"\n## 财务信号\n- 信号: {sig.signal}, 置信度: {sig.confidence}")
        else:
            parts.append("\n**暂无报告中的财务分析。**")

        return "\n".join(parts)

    def _assemble_quant(self, ctx: DataContext, base_info: str, now: datetime) -> str:
        """量化分析师：技术指标 + 技术分析详情。"""
        parts = [base_info]
        ctx.data_refs.append("base_info")

        report = ctx.latest_report
        if report:
            ctx.data_refs.append(f"report_{report.id}")
            self._check_report_staleness(ctx, report, now)

            if report.technical_detail:
                ctx.data_refs.append("technical_detail")
                detail = report.technical_detail
                if isinstance(detail, dict):
                    parts.append("\n## 技术面分析")
                    if "trend" in detail:
                        parts.append(f"- 趋势: {detail.get('trend', '')} (强度: {detail.get('trend_strength', '')})")
                    if "key_levels" in detail:
                        levels = detail["key_levels"]
                        if levels.get("support"):
                            parts.append(f"- 支撑位: {levels['support']}")
                        if levels.get("resistance"):
                            parts.append(f"- 阻力位: {levels['resistance']}")
                    if "indicators" in detail:
                        parts.append(f"- 指标: {json.dumps(detail['indicators'], ensure_ascii=False)}")
                    if "pattern" in detail:
                        parts.append(f"- 形态: {detail.get('pattern', '')}")

            if report.analyst_signals and report.analyst_signals.technical:
                sig = report.analyst_signals.technical
                parts.append(f"\n## 技术信号\n- 信号: {sig.signal}, 置信度: {sig.confidence}")
        else:
            parts.append("\n**暂无技术面分析数据。**")

        return "\n".join(parts)

    def _assemble_sentiment(self, ctx: DataContext, base_info: str, now: datetime) -> str:
        """情绪分析师：雪球分析 + 情绪信号。"""
        parts = [base_info]
        ctx.data_refs.append("base_info")

        report = ctx.latest_report
        if report:
            ctx.data_refs.append(f"report_{report.id}")
            self._check_report_staleness(ctx, report, now)

            if report.xueqiu_detail:
                ctx.data_refs.append("xueqiu_detail")
                parts.append(f"\n## 雪球情绪分析\n{report.xueqiu_detail}")

            if report.news_detail:
                ctx.data_refs.append("news_detail")
                parts.append(f"\n## 新闻情绪\n{report.news_detail}")

            if report.analyst_signals:
                sigs = report.analyst_signals
                if sigs.sentiment:
                    parts.append(f"\n## 情绪信号\n- 雪球: {sigs.sentiment.signal} (置信度: {sigs.sentiment.confidence})")
                if sigs.news:
                    parts.append(f"- 新闻: {sigs.news.signal} (置信度: {sigs.news.confidence})")
        else:
            parts.append("\n**暂无情绪分析数据。**")

        return "\n".join(parts)

    def _assemble_debate(
        self, ctx: DataContext, base_info: str, reflection_repo, now: datetime
    ) -> str:
        """多空辩手：Bull/Bear 辩论 + 反思记忆。"""
        parts = [base_info]
        ctx.data_refs.append("base_info")

        report = ctx.latest_report
        if report:
            ctx.data_refs.append(f"report_{report.id}")
            self._check_report_staleness(ctx, report, now)

            if report.debate_detail:
                ctx.data_refs.append("debate_detail")
                detail = report.debate_detail
                if isinstance(detail, dict):
                    if "bull" in detail:
                        bull = detail["bull"]
                        parts.append(f"\n## 看多论述")
                        if isinstance(bull, dict):
                            parts.append(f"**论点**: {bull.get('thesis', '')}")
                            if bull.get("supporting_evidence"):
                                for ev in bull["supporting_evidence"][:5]:
                                    parts.append(f"- {ev}")
                            if bull.get("catalysts"):
                                parts.append(f"**催化剂**: {', '.join(bull['catalysts'][:3])}")

                    if "bear" in detail:
                        bear = detail["bear"]
                        parts.append(f"\n## 看空论述")
                        if isinstance(bear, dict):
                            parts.append(f"**论点**: {bear.get('thesis', '')}")
                            if bear.get("risk_factors"):
                                for rf in bear["risk_factors"][:5]:
                                    parts.append(f"- {rf}")

            # 各路信号汇总（辩论角色需要看全局）
            if report.signal_summary:
                ss = report.signal_summary
                parts.append(f"\n## 五路信号汇总")
                parts.append(f"- 新闻: {ss.news_signal}")
                parts.append(f"- 财务: {ss.financial_signal}")
                parts.append(f"- 情绪: {ss.sentiment_signal}")
                parts.append(f"- 技术: {ss.technical_signal}")
                parts.append(f"- 辩论倾向: {ss.debate_lean}")
                parts.append(f"- 综合: {ss.overall_signal} (置信度: {ss.overall_confidence})")

            # 反思记忆
            try:
                fw = ctx.framework
                for role_key in ["bull", "bear", "risk_advisor"]:
                    memories = reflection_repo.get_by_framework_and_role(fw.id, role_key, limit=2)
                    if memories:
                        parts.append(f"\n## {role_key} 历史教训")
                        for m in memories:
                            parts.append(f"- {m.reflection[:150]}")
            except Exception as e:
                logger.warning(f"加载反思记忆失败: {e}")
        else:
            parts.append("\n**暂无多空辩论数据。**")

        return "\n".join(parts)

    def _assemble_competitor(self, ctx: DataContext, base_info: str) -> str:
        """竞品分析师：竞争对手信息（占位，数据源待扩展）。"""
        parts = [base_info]
        ctx.data_refs.append("base_info")

        fw = ctx.framework
        if fw.competitors:
            parts.append(f"\n## 主要竞争对手\n{', '.join(fw.competitors)}")

        parts.append("\n**注意**: 竞品对比功能正在建设中，目前只能基于已有报告中的信息进行定性分析。")
        return "\n".join(parts)

    def _check_report_staleness(self, ctx: DataContext, report: InvestmentReport, now: datetime) -> None:
        """检查报告数据新鲜度。"""
        if report.report_date:
            age_days = (now - report.report_date).days
            if age_days > REPORT_STALE_DAYS:
                ctx.stale_warnings.append({
                    "type": "report_stale",
                    "message": f"报告数据已过期（{age_days}天前，{report.report_date.strftime('%Y-%m-%d')}）",
                    "action": "建议重新生成投研报告以获取最新分析",
                    "age_days": age_days,
                })

    def _check_financial_staleness(self, ctx: DataContext, fw: AnalysisFramework, now: datetime) -> None:
        """检查财务数据新鲜度。"""
        if fw.financial_fetched_at:
            fetched = fw.financial_fetched_at
            if isinstance(fetched, str):
                fetched = datetime.fromisoformat(fetched)
            age_days = (now - fetched).days
            if age_days > FINANCIAL_STALE_DAYS:
                ctx.stale_warnings.append({
                    "type": "financial_stale",
                    "message": f"财务数据已过期（{age_days}天前获取）",
                    "action": "refresh_financial",
                    "age_days": age_days,
                })

    def _fetch_realtime_quote(self, stock_code: str) -> str:
        """获取实时行情，格式化为文本。失败时返回空字符串。"""
        if not stock_code:
            return ""
        try:
            quote = self._quote_service.fetch_quote(stock_code)
            if quote.get("error"):
                logger.warning("获取实时行情失败 [%s]: %s", stock_code, quote["error"])
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
        except Exception as e:
            logger.warning("获取实时行情异常 [%s]: %s", stock_code, e)
            return ""

    def _fetch_dividend_history(self, stock_code: str) -> str:
        """获取分红历史数据，格式化为文本。失败时返回空字符串。"""
        if not stock_code:
            return ""
        try:
            result = self._dividend_service.fetch_dividend(stock_code)
            if result.get("error"):
                logger.info("获取分红历史失败 [%s]: %s", stock_code, result["error"])
                return ""

            dividends = result.get("dividends", [])
            yield_trend = result.get("yield_trend", [])
            summary = result.get("summary", {})

            if not dividends:
                return ""

            lines = ["\n## 分红历史数据"]

            # 汇总信息
            if summary.get("total_count"):
                lines.append(f"- 累计分红次数: {summary['total_count']}次")
            if summary.get("total_cash_per_share"):
                lines.append(f"- 累计每股现金分红: {summary['total_cash_per_share']:.4f}元")
            if summary.get("avg_annual_cash"):
                lines.append(f"- 年均每股分红: {summary['avg_annual_cash']:.4f}元")

            # 按年度的分红趋势（最近 5 年）
            if yield_trend:
                lines.append("\n### 各年度每股分红")
                for item in yield_trend[:5]:
                    lines.append(f"- {item['year']}年: {item['cash_per_share']:.4f}元/股")

            # 最近 3 条分红明细
            lines.append("\n### 最近分红明细")
            for d in dividends[:3]:
                parts_d = []
                if d.get("announce_date"):
                    parts_d.append(f"公告日: {d['announce_date']}")
                if d.get("cash_per_share"):
                    parts_d.append(f"派息: {d['cash_per_share']}元/股")
                if d.get("bonus_shares"):
                    parts_d.append(f"送股: {d['bonus_shares']}")
                if d.get("transfer_shares"):
                    parts_d.append(f"转增: {d['transfer_shares']}")
                if d.get("ex_date"):
                    parts_d.append(f"除权日: {d['ex_date']}")
                if d.get("status"):
                    parts_d.append(f"进度: {d['status']}")
                if parts_d:
                    lines.append(f"- {' | '.join(parts_d)}")

            return "\n".join(lines)
        except Exception as e:
            logger.warning("获取分红历史异常 [%s]: %s", stock_code, e)
            return ""

    def _fetch_live_financial(self, stock_code: str) -> str:
        """实时获取最新财报数据。失败时返回空字符串。"""
        if not stock_code:
            return ""
        try:
            summary = self._financial_service.fetch_summary(stock_code)
            return summary or ""
        except Exception as e:
            logger.warning("获取财报数据异常 [%s]: %s", stock_code, e)
            return ""
