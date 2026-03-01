import logging
import threading
from dataclasses import dataclass, field
from queue import Queue

from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.presentation.markdown_renderer import save_report
from invest_research.services.analysis_service import AnalysisService
from invest_research.services.claude_client import ClaudeClient
from invest_research.services.crawl_service import CrawlService
from invest_research.services.framework_service import FrameworkService
from invest_research.services.report_service import ReportService
from invest_research.services.financial_service import FinancialDataService

logger = logging.getLogger(__name__)

STEP_BUILD_FRAMEWORK = "build_framework"
STEP_CRAWL_NEWS = "crawl_news"
STEP_ANALYZE = "analyze"
STEP_GENERATE_REPORT = "generate_report"
STEP_DONE = "done"
STEP_ERROR = "error"


@dataclass
class ProgressEvent:
    step: str
    message: str
    report_id: int | None = None
    articles: list[dict] | None = None


@dataclass
class ResearchTask:
    task_id: str
    company_name: str
    auto_weekly: bool = False
    queue: Queue = field(default_factory=Queue)


class ResearchPipeline:
    def __init__(self):
        self._tasks: dict[str, ResearchTask] = {}

    def start(self, task_id: str, company_name: str, auto_weekly: bool = False) -> ResearchTask:
        task = ResearchTask(task_id=task_id, company_name=company_name, auto_weekly=auto_weekly)
        self._tasks[task_id] = task
        thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        thread.start()
        return task

    def get_task(self, task_id: str) -> ResearchTask | None:
        return self._tasks.get(task_id)

    def _run(self, task: ResearchTask) -> None:
        conn = init_db()
        try:
            self._execute_pipeline(task, conn)
        except Exception as e:
            logger.error(f"研究流水线失败 [{task.company_name}]: {e}")
            task.queue.put(ProgressEvent(step=STEP_ERROR, message=str(e)))
        finally:
            conn.close()

    def _execute_pipeline(self, task: ResearchTask, conn) -> None:
        framework_repo = FrameworkRepo(conn)
        news_repo = NewsRepo(conn)
        analysis_repo = AnalysisRepo(conn)
        report_repo = ReportRepo(conn)
        claude = ClaudeClient()

        # 步骤 1: 构建框架
        task.queue.put(ProgressEvent(
            step=STEP_BUILD_FRAMEWORK,
            message=f"正在为 {task.company_name} 构建分析框架...",
        ))

        framework_service = FrameworkService(claude)
        framework = framework_service.build_framework_auto(task.company_name)
        framework.is_active = task.auto_weekly
        framework_id = framework_repo.save(framework)
        framework.id = framework_id

        task.queue.put(ProgressEvent(
            step=STEP_BUILD_FRAMEWORK,
            message=f"框架构建完成：{framework.industry} - {framework.sub_industry}",
        ))

        # 步骤 2: 爬取新闻
        task.queue.put(ProgressEvent(
            step=STEP_CRAWL_NEWS,
            message="正在爬取相关新闻...",
        ))

        def on_source_complete(source_name: str, articles: list) -> None:
            task.queue.put(ProgressEvent(
                step=STEP_CRAWL_NEWS,
                message=f"{source_name} 返回 {len(articles)} 条新闻",
                articles=[
                    {"title": a.title, "url": a.url, "source": a.source}
                    for a in articles
                ],
            ))

        crawl_service = CrawlService(news_repo)
        count = crawl_service.crawl_all(framework, on_source_complete=on_source_complete)

        task.queue.put(ProgressEvent(
            step=STEP_CRAWL_NEWS,
            message=f"新闻爬取完成，新增 {count} 条",
        ))

        # 获取财务数据
        task.queue.put(ProgressEvent(
            step=STEP_CRAWL_NEWS,
            message="正在获取财务数据...",
        ))
        financial_service = FinancialDataService()
        financial_context = financial_service.fetch_summary(framework.stock_code)
        if financial_context:
            task.queue.put(ProgressEvent(
                step=STEP_CRAWL_NEWS,
                message="财务数据获取完成",
            ))

        # 步骤 3: AI 分析
        task.queue.put(ProgressEvent(
            step=STEP_ANALYZE,
            message="正在进行 AI 分析...",
        ))

        analysis_service = AnalysisService(claude, news_repo, analysis_repo)
        analysis = analysis_service.analyze_week(framework, financial_context=financial_context)

        task.queue.put(ProgressEvent(
            step=STEP_ANALYZE,
            message=f"分析完成，处理了 {len(analysis.news_analyses)} 条新闻",
        ))

        # 步骤 4: 生成报告
        task.queue.put(ProgressEvent(
            step=STEP_GENERATE_REPORT,
            message="正在生成投资报告...",
        ))

        report_service = ReportService(claude, analysis_repo, report_repo, news_repo)
        report = report_service.generate_report(framework, financial_context=financial_context)
        save_report(report, framework)

        task.queue.put(ProgressEvent(
            step=STEP_GENERATE_REPORT,
            message=f"报告生成完成，评级: {report.investment_rating}",
            report_id=report.id,
        ))

        # 完成
        task.queue.put(ProgressEvent(
            step=STEP_DONE,
            message="研究流程全部完成",
            report_id=report.id,
        ))
