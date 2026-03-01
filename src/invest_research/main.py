import logging
import signal
import sys
import time

import click
from rich.console import Console

from invest_research.config import get_settings
from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.presentation import cli as cli_ui
from invest_research.presentation.markdown_renderer import save_report
from invest_research.services.claude_client import ClaudeClient
from invest_research.services.crawl_service import CrawlService
from invest_research.services.analysis_service import AnalysisService
from invest_research.services.framework_service import FrameworkService
from invest_research.services.report_service import ReportService

console = Console()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


@click.group()
def cli():
    """AI 投研分析系统"""
    pass


@cli.command("init-framework")
@click.argument("company_name")
def init_framework(company_name: str):
    """交互式构建分析框架"""
    conn = init_db()
    try:
        claude = ClaudeClient()
        framework_service = FrameworkService(claude)
        framework_repo = FrameworkRepo(conn)

        cli_ui.display_info(f"开始为 [{company_name}] 构建分析框架...")
        cli_ui.display_info("输入 'quit' 可提前结束对话，AI 将根据已有信息生成框架。\n")

        framework = framework_service.build_framework(
            company_name=company_name,
            user_input_fn=cli_ui.get_user_input,
            display_fn=cli_ui.display_ai_message,
        )

        framework_id = framework_repo.save(framework)
        framework.id = framework_id

        cli_ui.display_framework(framework)
        cli_ui.display_success(f"框架已保存，ID: {framework_id}")
    finally:
        conn.close()


@cli.command("list-frameworks")
def list_frameworks():
    """列出所有分析框架"""
    conn = init_db()
    try:
        repo = FrameworkRepo(conn)
        frameworks = repo.list_all()
        cli_ui.display_frameworks_list(frameworks)
    finally:
        conn.close()


@cli.command("run-crawl")
@click.option("--framework-id", required=True, type=int, help="分析框架 ID")
def run_crawl(framework_id: int):
    """手动触发新闻爬取"""
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        framework = framework_repo.get_by_id(framework_id)
        if not framework:
            cli_ui.display_error(f"未找到框架 ID: {framework_id}")
            return

        news_repo = NewsRepo(conn)
        crawl_service = CrawlService(news_repo)

        cli_ui.display_info(f"开始为 [{framework.company_name}] 爬取新闻...")
        count = crawl_service.crawl_all(framework)
        cli_ui.display_success(f"爬取完成，新增 {count} 条新闻")
    finally:
        conn.close()


@cli.command("run-analysis")
@click.option("--framework-id", required=True, type=int, help="分析框架 ID")
def run_analysis(framework_id: int):
    """手动触发新闻分析"""
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        framework = framework_repo.get_by_id(framework_id)
        if not framework:
            cli_ui.display_error(f"未找到框架 ID: {framework_id}")
            return

        claude = ClaudeClient()
        news_repo = NewsRepo(conn)
        analysis_repo = AnalysisRepo(conn)
        analysis_service = AnalysisService(claude, news_repo, analysis_repo)

        cli_ui.display_info(f"开始分析 [{framework.company_name}] 的新闻...")
        analysis = analysis_service.analyze_week(framework)
        cli_ui.display_success(
            f"分析完成: {len(analysis.news_analyses)} 条新闻\n"
            f"周度总结: {analysis.weekly_summary}"
        )
    finally:
        conn.close()


@cli.command("generate-report")
@click.option("--framework-id", required=True, type=int, help="分析框架 ID")
def generate_report(framework_id: int):
    """生成投资报告"""
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        framework = framework_repo.get_by_id(framework_id)
        if not framework:
            cli_ui.display_error(f"未找到框架 ID: {framework_id}")
            return

        claude = ClaudeClient()
        analysis_repo = AnalysisRepo(conn)
        report_repo = ReportRepo(conn)
        news_repo = NewsRepo(conn)
        report_service = ReportService(claude, analysis_repo, report_repo, news_repo)

        cli_ui.display_info(f"开始为 [{framework.company_name}] 生成投资报告...")
        report = report_service.generate_report(framework)
        filepath = save_report(report, framework)
        cli_ui.display_report_saved(filepath)
    finally:
        conn.close()


@cli.command("schedule-start")
def schedule_start():
    """启动定时任务（独立模式）"""
    from invest_research.scheduler.jobs import create_scheduler

    settings = get_settings()
    scheduler = create_scheduler()
    scheduler.start()

    cli_ui.display_info("定时任务已启动:")
    cli_ui.display_info(f"  - 每周投研: 每周{settings.schedule_weekly_day} {settings.schedule_weekly_hour}:00")
    cli_ui.display_info("按 Ctrl+C 停止...")

    def handle_signal(signum, frame):
        scheduler.shutdown()
        cli_ui.display_info("定时任务已停止")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while True:
        time.sleep(1)


@cli.command("serve")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8001, type=int, help="监听端口")
def serve(host: str, port: int):
    """启动 Web 服务（含定时投研调度）"""
    import uvicorn
    from invest_research.presentation.web import create_app
    from invest_research.scheduler.jobs import create_scheduler

    settings = get_settings()
    init_db()

    scheduler = create_scheduler()
    scheduler.start()

    next_run = scheduler.get_job("weekly_research").next_run_time
    cli_ui.display_info(
        f"定时投研已启动: 每周{settings.schedule_weekly_day} "
        f"{settings.schedule_weekly_hour}:00，下次执行: {next_run}"
    )
    cli_ui.display_info(f"Web 服务启动: http://{host}:{port}")

    try:
        uvicorn.run(create_app(), host=host, port=port, log_level="info")
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    cli()
