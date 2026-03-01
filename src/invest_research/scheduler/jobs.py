import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore

from invest_research.config import get_settings
from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.services.analysis_service import AnalysisService
from invest_research.services.claude_client import ClaudeClient
from invest_research.services.crawl_service import CrawlService
from invest_research.services.financial_service import FinancialDataService
from invest_research.services.report_service import ReportService
from invest_research.presentation.markdown_renderer import save_report

logger = logging.getLogger(__name__)


def run_weekly_research_job() -> None:
    """每周定时任务：对所有活跃框架执行完整投研流程。"""
    logger.info("定时任务: 开始每周投研分析")
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        frameworks = framework_repo.list_all()
        active_frameworks = [fw for fw in frameworks if fw.is_active]

        if not active_frameworks:
            logger.info("无活跃分析框架，跳过本周投研")
            return

        news_repo = NewsRepo(conn)
        analysis_repo = AnalysisRepo(conn)
        report_repo = ReportRepo(conn)
        claude = ClaudeClient()
        crawl_service = CrawlService(news_repo)
        financial_service = FinancialDataService()
        analysis_service = AnalysisService(claude, news_repo, analysis_repo)
        report_service = ReportService(claude, analysis_repo, report_repo, news_repo)

        for fw in active_frameworks:
            try:
                _process_framework(
                    fw, crawl_service, financial_service,
                    analysis_service, report_service,
                )
            except Exception as e:
                logger.error(f"[{fw.company_name}] 投研流程失败: {e}")
    finally:
        conn.close()

    logger.info("定时任务: 每周投研分析完成")


def _process_framework(fw, crawl_service, financial_service, analysis_service, report_service):
    """对单个框架执行完整投研流程：爬取 → 财务数据 → 分析 → 报告。"""
    logger.info(f"[{fw.company_name}] 开始投研流程")

    # 1. 爬取新闻
    count = crawl_service.crawl_all(fw)
    logger.info(f"[{fw.company_name}] 新增 {count} 条新闻")

    # 2. 获取财务数据
    financial_context = financial_service.fetch_summary(fw.stock_code)

    # 3. AI 周度分析
    analysis_service.analyze_week(fw, financial_context=financial_context)

    # 4. 生成投研报告
    report = report_service.generate_report(fw, financial_context=financial_context)
    filepath = save_report(report, fw)
    logger.info(f"[{fw.company_name}] 报告已保存: {filepath}")


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()

    scheduler = BackgroundScheduler(jobstores={"default": MemoryJobStore()})

    scheduler.add_job(
        run_weekly_research_job,
        "cron",
        day_of_week=settings.schedule_weekly_day,
        hour=settings.schedule_weekly_hour,
        id="weekly_research",
        replace_existing=True,
    )

    return scheduler
