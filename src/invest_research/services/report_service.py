import json
import logging
from datetime import datetime

from invest_research.config import get_settings
from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.models import (
    AnalysisFramework,
    InvestmentReport,
    RiskItem,
    OpportunityItem,
)
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class ReportService:
    def __init__(
        self,
        claude_client: ClaudeClient,
        analysis_repo: AnalysisRepo,
        report_repo: ReportRepo,
    ):
        self.claude = claude_client
        self.analysis_repo = analysis_repo
        self.report_repo = report_repo
        self.settings = get_settings()

    def generate_report(self, framework: AnalysisFramework) -> InvestmentReport:
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

        # 获取上期报告
        previous_report = self.report_repo.get_latest(framework.id)
        previous_context = "无上期报告。"
        previous_rating = ""
        if previous_report:
            previous_rating = previous_report.investment_rating
            previous_context = (
                f"上期评级: {previous_report.investment_rating}\n"
                f"上期摘要: {previous_report.executive_summary}\n"
                f"上期主要风险: {', '.join(r.description for r in previous_report.risks[:3])}\n"
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

        # 本周分析详情
        current_analysis_detail = ""
        for item in latest_analysis.news_analyses:
            current_analysis_detail += (
                f"- [{item.sentiment}] [{item.category}] {item.title}: {item.summary}\n"
            )

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 上期报告\n{previous_context}\n\n"
            f"## 历史周度摘要 (近 {len(historical)} 周)\n{historical_summaries}\n\n"
            f"## 本周分析详情\n{current_analysis_detail}\n"
            f"## 本周总结\n{latest_analysis.weekly_summary}\n\n"
            f"请基于以上信息生成投资研究报告。"
        )

        messages = [{"role": "user", "content": user_message}]

        response = self.claude.chat(
            messages=messages,
            prompt_name="risk_advisor",
            model=self.settings.claude_model_heavy,
        )

        report = self._parse_report(response, framework.id, previous_rating)

        # 保存报告
        self.report_repo.save(report)
        logger.info(f"报告生成完成: {framework.company_name}，评级: {report.investment_rating}")
        return report

    @staticmethod
    def _parse_report(
        response: str,
        framework_id: int,
        previous_rating: str,
    ) -> InvestmentReport:
        try:
            json_str = ClaudeClient._extract_json(response)
            data = json.loads(json_str)

            risks = [RiskItem(**r) for r in data.get("risks", [])]
            opportunities = [OpportunityItem(**o) for o in data.get("opportunities", [])]

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
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"报告解析失败: {e}")
            return InvestmentReport(
                framework_id=framework_id,
                report_date=datetime.now(),
                investment_rating="中性",
                rating_rationale=f"报告解析失败: {e}",
                executive_summary=response[:500],
                previous_rating=previous_rating,
            )
