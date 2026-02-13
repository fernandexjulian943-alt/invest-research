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
    ) -> WeeklyAnalysis:
        if week_end is None:
            week_end = datetime.now()
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

        # 构建新闻列表
        news_list = []
        for i, article in enumerate(articles):
            news_list.append({
                "id": i + 1,
                "title": article.title,
                "source": article.source,
                "snippet": article.content_snippet[:200],
                "date": article.published_at.strftime("%Y-%m-%d") if article.published_at else "",
            })

        # 构建消息
        framework_context = (
            f"目标公司: {framework.company_name}\n"
            f"行业: {framework.industry} - {framework.sub_industry}\n"
            f"主营业务: {framework.business_description}\n"
            f"竞争对手: {', '.join(framework.competitors)}\n"
            f"宏观因素: {', '.join(framework.macro_factors)}\n"
        )

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 历史摘要\n{historical_context}\n\n"
            f"## 本周新闻 ({len(news_list)} 条)\n"
            f"```json\n{json.dumps(news_list, ensure_ascii=False, indent=2)}\n```\n\n"
            f"请对每条新闻进行分析，并生成周度总结。"
        )

        messages = [{"role": "user", "content": user_message}]

        response = self.claude.chat(
            messages=messages,
            prompt_name="news_analyst",
            model=self.settings.claude_model_light,
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
            logger.error(f"分析结果解析失败: {e}")
            return WeeklyAnalysis(
                framework_id=framework_id,
                week_start=week_start,
                week_end=week_end,
                news_analyses=[],
                weekly_summary=f"分析结果解析失败: {response[:200]}",
            )
