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
from invest_research.services.report_service import ReportService
from invest_research.presentation.markdown_renderer import save_report

logger = logging.getLogger(__name__)


def run_crawl_job() -> None:
    logger.info("定时任务: 开始爬取新闻")
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        news_repo = NewsRepo(conn)

        frameworks = framework_repo.list_all()
        if not frameworks:
            logger.info("无分析框架，跳过爬取")
            return

        crawl_service = CrawlService(news_repo)
        for fw in frameworks:
            try:
                count = crawl_service.crawl_all(fw)
                logger.info(f"[{fw.company_name}] 新增 {count} 条新闻")
            except Exception as e:
                logger.error(f"[{fw.company_name}] 爬取失败: {e}")
    finally:
        conn.close()


def run_analysis_and_report_job() -> None:
    logger.info("定时任务: 开始分析与生成报告")
    settings = get_settings()
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        news_repo = NewsRepo(conn)
        analysis_repo = AnalysisRepo(conn)
        report_repo = ReportRepo(conn)
        claude = ClaudeClient()

        analysis_service = AnalysisService(claude, news_repo, analysis_repo)
        report_service = ReportService(claude, analysis_repo, report_repo)

        frameworks = framework_repo.list_all()
        for fw in frameworks:
            try:
                analysis_service.analyze_week(fw)
                report = report_service.generate_report(fw)
                filepath = save_report(report, fw)
                logger.info(f"[{fw.company_name}] 报告已保存: {filepath}")
            except Exception as e:
                logger.error(f"[{fw.company_name}] 分析/报告生成失败: {e}")
    finally:
        conn.close()


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()

    scheduler = BackgroundScheduler(jobstores={"default": MemoryJobStore()})

    # 每周日 20:00 爬取新闻
    scheduler.add_job(
        run_crawl_job,
        "cron",
        day_of_week=settings.schedule_crawl_day,
        hour=settings.schedule_crawl_hour,
        id="weekly_crawl",
        replace_existing=True,
    )

    # 每周一 08:00 分析+生成报告
    scheduler.add_job(
        run_analysis_and_report_job,
        "cron",
        day_of_week=settings.schedule_report_day,
        hour=settings.schedule_report_hour,
        id="weekly_report",
        replace_existing=True,
    )

    return scheduler
