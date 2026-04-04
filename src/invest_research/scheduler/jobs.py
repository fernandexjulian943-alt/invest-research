import logging
import time
from pathlib import Path

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
from invest_research.services.qq_notify import notify as qq_notify
from invest_research.presentation.markdown_renderer import save_report

logger = logging.getLogger(__name__)

LOCK_FILE = Path("/tmp/invest-research-running.lock")

# 24小时内错过的任务都补执行
MISFIRE_GRACE_TIME = 86400


def run_weekly_research_job() -> None:
    """每周定时任务：对所有活跃框架执行完整投研流程。"""
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("定时任务: 开始每周投研分析")
    logger.info("=" * 60)

    # 创建锁文件，防止健康检查误杀
    try:
        LOCK_FILE.write_text(str(int(start_time)))
        logger.info("锁文件已创建: %s", LOCK_FILE)
    except Exception as e:
        logger.warning("创建锁文件失败: %s", e)

    conn = init_db()
    success_count = 0
    fail_count = 0
    results: list[tuple[str, str]] = []  # (公司名, 评级或"失败")
    try:
        framework_repo = FrameworkRepo(conn)
        frameworks = framework_repo.list_all()
        active_frameworks = [fw for fw in frameworks if fw.is_active]

        if not active_frameworks:
            logger.info("无活跃分析框架，跳过本周投研")
            return

        logger.info("共 %d 个活跃框架待处理", len(active_frameworks))

        news_repo = NewsRepo(conn)
        analysis_repo = AnalysisRepo(conn)
        report_repo = ReportRepo(conn)
        claude = ClaudeClient()
        crawl_service = CrawlService(news_repo)
        financial_service = FinancialDataService()
        analysis_service = AnalysisService(claude, news_repo, analysis_repo)
        report_service = ReportService(claude, analysis_repo, report_repo, news_repo)

        for i, fw in enumerate(active_frameworks, 1):
            logger.info("[%d/%d] 开始处理: %s", i, len(active_frameworks), fw.company_name)
            fw_start = time.time()
            try:
                report = _process_framework(
                    fw, crawl_service, financial_service,
                    analysis_service, report_service,
                )
                elapsed = time.time() - fw_start
                logger.info("[%s] 处理完成，耗时 %.1f 秒", fw.company_name, elapsed)
                success_count += 1
                rating = report.investment_rating if report else "未知"
                results.append((fw.company_name, rating))
            except Exception as e:
                elapsed = time.time() - fw_start
                fail_count += 1
                results.append((fw.company_name, "失败"))
                logger.error(
                    "[%s] 投研流程失败（耗时 %.1f 秒）: %s",
                    fw.company_name, elapsed, e, exc_info=True,
                )

            # 框架间休息 30 秒，降低服务器和外部 API 压力
            if i < len(active_frameworks):
                logger.info("休息 30 秒后处理下一个框架...")
                time.sleep(30)
    finally:
        conn.close()
        # 删除锁文件
        try:
            LOCK_FILE.unlink(missing_ok=True)
            logger.info("锁文件已删除")
        except Exception as e:
            logger.warning("删除锁文件失败: %s", e)

    total_elapsed = time.time() - start_time
    total_min = total_elapsed / 60
    logger.info("=" * 60)
    logger.info(
        "定时任务完成: 成功 %d, 失败 %d, 总耗时 %.1f 秒",
        success_count, fail_count, total_elapsed,
    )
    if fail_count > 0:
        logger.warning("有 %d 个框架处理失败，请检查上方日志", fail_count)
    logger.info("=" * 60)

    # QQ 通知
    lines = [f"📊 每周投研完成 | 成功 {success_count} 失败 {fail_count} | 耗时 {total_min:.0f} 分钟"]
    for name, rating in results:
        lines.append(f"  {name}: {rating}")
    try:
        qq_notify("\n".join(lines))
    except Exception as e:
        logger.error("QQ 通知发送失败: %s", e)


def _process_framework(fw, crawl_service, financial_service, analysis_service, report_service):
    """对单个框架执行完整投研流程：爬取 → 财务数据 → 分析 → 报告。返回报告对象。"""
    logger.info("[%s] 开始投研流程", fw.company_name)

    # 1. 爬取新闻
    count = crawl_service.crawl_all(fw)
    logger.info("[%s] 新增 %d 条新闻", fw.company_name, count)

    # 2. 获取财务数据
    financial_context = financial_service.fetch_summary(fw.stock_code)

    # 3. AI 周度分析
    analysis_service.analyze_week(fw, financial_context=financial_context)

    # 4. 生成投研报告
    report = report_service.generate_report(fw, financial_context=financial_context)
    filepath = save_report(report, fw)
    logger.info("[%s] 报告已保存: %s", fw.company_name, filepath)
    return report


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
        misfire_grace_time=MISFIRE_GRACE_TIME,
        coalesce=True,
    )

    return scheduler
