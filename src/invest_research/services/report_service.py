import json
import logging
from datetime import datetime

from invest_research.config import get_settings
from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.models import (
    AnalysisFramework,
    InvestmentReport,
    RiskItem,
    OpportunityItem,
    NewsReference,
)
from invest_research.services.analysis_service import AnalysisService
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class ReportService:
    def __init__(
        self,
        claude_client: ClaudeClient,
        analysis_repo: AnalysisRepo,
        report_repo: ReportRepo,
        news_repo: NewsRepo,
    ):
        self.claude = claude_client
        self.analysis_repo = analysis_repo
        self.report_repo = report_repo
        self.news_repo = news_repo
        self.settings = get_settings()

    def generate_report(self, framework: AnalysisFramework, financial_context: str = "") -> InvestmentReport:
        # 获取最新周分析
        latest_analysis = self.analysis_repo.get_latest(framework.id)
        if not latest_analysis:
            raise ValueError(f"框架 {framework.id} ({framework.company_name}) 无分析数据，请先运行分析")

        # 获取历史分析摘要
        historical = self.analysis_repo.get_recent(
            framework.id, weeks=self.settings.analysis_rolling_weeks
        )
        historical_summaries = "\n".join(
            f"[{a.week_end.strftime('%Y-%m-%d')}] {a.weekly_summary}"
            for a in reversed(historical)
        )

        # 获取上期报告（完整上下文用于差异对比）
        previous_report = self.report_repo.get_latest(framework.id)
        previous_context = "无上期报告。"
        previous_rating = ""
        if previous_report:
            previous_rating = previous_report.investment_rating
            prev_risks = "\n".join(
                f"- [{r.severity}] {r.description}: {r.impact}"
                for r in previous_report.risks
            )
            prev_opps = "\n".join(
                f"- [{o.confidence}] {o.description}: {o.impact}"
                for o in previous_report.opportunities
            )
            previous_context = (
                f"上期评级: {previous_report.investment_rating}\n"
                f"上期评级理由: {previous_report.rating_rationale}\n"
                f"上期摘要: {previous_report.executive_summary}\n"
                f"上期风险:\n{prev_risks}\n"
                f"上期机会:\n{prev_opps}\n"
                f"上期详细分析: {previous_report.detailed_analysis}\n"
            )

        # 构建框架上下文
        framework_context = (
            f"公司: {framework.company_name} ({framework.stock_code})\n"
            f"行业: {framework.industry} - {framework.sub_industry}\n"
            f"主营业务: {framework.business_description}\n"
            f"竞争对手: {', '.join(framework.competitors)}\n"
            f"宏观因素: {', '.join(framework.macro_factors)}\n"
            f"监控指标: {', '.join(framework.monitoring_indicators)}\n"
        )

        # 获取本周实际新闻文章（带 URL）
        articles = self.news_repo.get_by_framework(
            framework.id,
            start_date=latest_analysis.week_start,
            end_date=latest_analysis.week_end,
        )

        # 构建新闻链接参考列表，供 Claude 在 supporting_news 中引用
        news_url_lines = []
        for i, article in enumerate(articles):
            if article.url:
                snippet = article.content_snippet[:60].replace("\n", " ") if article.content_snippet else ""
                news_url_lines.append(f"[{i + 1}] {snippet} | URL: {article.url}")
        news_url_reference = "\n".join(news_url_lines) if news_url_lines else "无可用链接"

        # 本周分析详情
        current_analysis_detail = ""
        for item in latest_analysis.news_analyses:
            current_analysis_detail += (
                f"- [{item.sentiment}] [{item.category}] {item.title}: {item.summary}\n"
            )

        has_previous = previous_report is not None
        diff_instruction = ""
        if has_previous:
            diff_instruction = (
                "\n请在每个风险和机会的 supporting_news 中引用上方「新闻链接参考」中的具体新闻标题和 URL，"
                "并生成 changes_from_previous 字段总结与上期报告的差异，"
                "包括新增/消除的风险、新增/消失的机会、评级变动原因等。"
            )
        else:
            diff_instruction = (
                "\n请在每个风险和机会的 supporting_news 中引用上方「新闻链接参考」中的具体新闻标题和 URL。"
                "这是首次报告，changes_from_previous 填空字符串即可。"
            )

        financial_section = f"## 财务数据\n{financial_context}\n\n" if financial_context else ""

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"{financial_section}"
            f"## 上期报告\n{previous_context}\n\n"
            f"## 历史周度摘要 (近 {len(historical)} 周)\n{historical_summaries}\n\n"
            f"## 本周分析详情\n{current_analysis_detail}\n"
            f"## 本周总结\n{latest_analysis.weekly_summary}\n\n"
            f"## 新闻链接参考\n以下是本周所有新闻及其链接，请在 supporting_news 中从中选取相关链接：\n{news_url_reference}\n\n"
            f"请基于以上信息生成投资研究报告。{diff_instruction}"
        )

        messages = [{"role": "user", "content": user_message}]

        response = self.claude.chat(
            messages=messages,
            prompt_name="risk_advisor",
            model=self.settings.claude_model_heavy,
            max_tokens=8192,
        )

        report = self._parse_report(response, framework.id, previous_rating)

        # 保存报告
        self.report_repo.save(report)
        logger.info(f"报告生成完成: {framework.company_name}，评级: {report.investment_rating}")
        return report

    @staticmethod
    def _parse_risks(raw_risks: list[dict]) -> list[RiskItem]:
        risks = []
        for r in raw_risks:
            supporting = [NewsReference(**n) for n in r.pop("supporting_news", [])]
            risks.append(RiskItem(**r, supporting_news=supporting))
        return risks

    @staticmethod
    def _parse_opportunities(raw_opps: list[dict]) -> list[OpportunityItem]:
        opportunities = []
        for o in raw_opps:
            supporting = [NewsReference(**n) for n in o.pop("supporting_news", [])]
            opportunities.append(OpportunityItem(**o, supporting_news=supporting))
        return opportunities

    @staticmethod
    def _build_report(
        data: dict, framework_id: int, previous_rating: str,
    ) -> InvestmentReport:
        risks = ReportService._parse_risks(data.get("risks", []))
        opportunities = ReportService._parse_opportunities(data.get("opportunities", []))
        return InvestmentReport(
            framework_id=framework_id,
            report_date=datetime.now(),
            risks=risks,
            opportunities=opportunities,
            investment_rating=data.get("investment_rating", "中性"),
            rating_rationale=data.get("rating_rationale", ""),
            executive_summary=data.get("executive_summary", ""),
            detailed_analysis=data.get("detailed_analysis", ""),
            previous_rating=previous_rating,
            rating_change_reason=data.get("rating_change_reason", ""),
            changes_from_previous=data.get("changes_from_previous", ""),
        )

    @staticmethod
    def _fix_unescaped_quotes(json_str: str, max_attempts: int = 20) -> str:
        """迭代修复 JSON 字符串值中未转义的双引号。"""
        for _ in range(max_attempts):
            try:
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError as e:
                pos = e.pos
                if pos >= len(json_str):
                    break
                # 检查错误位置附近是否是字符串内的未转义引号
                # 向前找到最近的 ": " 开头（JSON key-value 结构）
                before = json_str[:pos]
                # 如果错误位置的字符是 " 且它不是值的结尾引号
                if json_str[pos] == '"':
                    # 查看后面是否紧跟 JSON 结构字符（说明这是合法关闭引号）
                    after_quote = json_str[pos + 1:pos + 3].lstrip()
                    if after_quote and after_quote[0] in (',', '}', ']', ':'):
                        # 这是合法的关闭引号，问题在前面；跳过
                        break
                    # 否则这个引号出现在字符串值内部，需要转义
                    json_str = json_str[:pos] + '\\"' + json_str[pos + 1:]
                elif pos > 0 and json_str[pos - 1] == '"':
                    # 引号在 pos-1 处
                    after_quote = json_str[pos:pos + 2].lstrip()
                    if after_quote and after_quote[0] not in (',', '}', ']', ':'):
                        json_str = json_str[:pos - 1] + '\\"' + json_str[pos:]
                    else:
                        break
                else:
                    break
        return json_str

    @staticmethod
    def _parse_report(
        response: str,
        framework_id: int,
        previous_rating: str,
    ) -> InvestmentReport:
        json_str = ClaudeClient._extract_json(response)
        try:
            data = json.loads(json_str)
            return ReportService._build_report(data, framework_id, previous_rating)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"报告 JSON 解析失败，尝试修复: {e}")
            # 先修复未转义的引号，再修复截断
            fixed = ReportService._fix_unescaped_quotes(json_str)
            repaired = AnalysisService._repair_json(fixed)
            try:
                data = json.loads(repaired)
                return ReportService._build_report(data, framework_id, previous_rating)
            except Exception as e2:
                logger.error(f"报告 JSON 修复后仍失败: {e2}")
                return InvestmentReport(
                    framework_id=framework_id,
                    report_date=datetime.now(),
                    investment_rating="中性",
                    rating_rationale=f"报告解析失败: {e}",
                    executive_summary=response[:500],
                    previous_rating=previous_rating,
                )
