import json
import logging
import threading
from dataclasses import dataclass, field
from queue import Queue

from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.models import AnalysisFramework, AnalystSignal, AnalystSignals
from invest_research.presentation.markdown_renderer import save_report
from invest_research.services.analysis_service import AnalysisService
from invest_research.services.claude_client import ClaudeClient
from invest_research.services.crawl_service import CrawlService
from invest_research.services.framework_service import FrameworkService
from invest_research.services.report_service import ReportService
from invest_research.services.financial_service import FinancialDataService
from invest_research.services.financial_analysis_service import FinancialAnalysisService
from invest_research.services.xueqiu_opinion_service import XueqiuOpinionService
from invest_research.services.stock_quote_service import StockQuoteService
from invest_research.services.stock_history_service import StockHistoryService
from invest_research.services.technical_analysis_service import TechnicalAnalysisService
from invest_research.services.debate_service import DebateService
from invest_research.data.reflection_repo import ReflectionRepo
from invest_research.services.reflection_service import ReflectionService

logger = logging.getLogger(__name__)

STEP_BUILD_FRAMEWORK = "build_framework"
STEP_CRAWL_NEWS = "crawl_news"
STEP_ANALYZE = "analyze"
STEP_GENERATE_REPORT = "generate_report"
STEP_DONE = "done"
STEP_ERROR = "error"

# 交互式任务状态
STATUS_CREATED = "created"
STATUS_COMPANY_LOADED = "company_loaded"
STATUS_STRATEGY_PROPOSED = "strategy_proposed"
STATUS_STRATEGY_CONFIRMED = "strategy_confirmed"
STATUS_CRAWLING = "crawling"
STATUS_ANALYZING = "analyzing"
STATUS_REPORT_DONE = "report_done"
STATUS_ERROR = "error"


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


@dataclass
class InteractiveTask:
    """交互式研究任务，支持分步确认。"""
    task_id: str
    stock_code: str
    investment_strategy: str = "balanced"
    status: str = STATUS_CREATED
    company_info: dict = field(default_factory=dict)
    strategy_draft: dict = field(default_factory=dict)  # AI 生成的框架草案
    framework: AnalysisFramework | None = None  # 确认后的框架
    framework_id: int | None = None
    auto_weekly: bool = False
    report_id: int | None = None
    error: str = ""
    queue: Queue = field(default_factory=Queue)  # SSE 事件队列


class ResearchPipeline:
    def __init__(self):
        self._tasks: dict[str, ResearchTask] = {}
        self._interactive_tasks: dict[str, InteractiveTask] = {}

    # ========== 原有全自动模式（不改） ==========

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

        # 后续步骤复用
        self._execute_from_crawl(task, framework, conn, claude)

    # ========== 交互式模式 ==========

    def create_interactive(self, task_id: str, stock_code: str, investment_strategy: str = "balanced") -> InteractiveTask:
        """创建交互式研究任务，自动获取公司信息和生成策略草案。"""
        itask = InteractiveTask(task_id=task_id, stock_code=stock_code, investment_strategy=investment_strategy)
        self._interactive_tasks[task_id] = itask
        # 在后台线程中获取公司信息 + 生成策略
        thread = threading.Thread(target=self._prepare_interactive, args=(itask,), daemon=True)
        thread.start()
        return itask

    def get_interactive_task(self, task_id: str) -> InteractiveTask | None:
        return self._interactive_tasks.get(task_id)

    def confirm_strategy(self, task_id: str, edits: dict, auto_weekly: bool = False) -> bool:
        """用户确认策略，合并编辑，保存框架并启动后续流程。"""
        itask = self._interactive_tasks.get(task_id)
        if not itask or itask.status != STATUS_STRATEGY_PROPOSED:
            return False

        itask.auto_weekly = auto_weekly

        # 合并用户编辑到策略草案
        draft = dict(itask.strategy_draft)
        for key in ("keywords", "competitors", "macro_factors", "monitoring_indicators",
                     "search_keywords"):
            if key in edits:
                draft[key] = edits[key]
        # search_keywords 映射到 keywords（框架模型用 keywords）
        if "search_keywords" in draft and "keywords" not in edits:
            draft["keywords"] = draft.pop("search_keywords")
        elif "search_keywords" in draft:
            draft.pop("search_keywords", None)

        # 构建 framework 对象
        framework = AnalysisFramework(
            company_name=draft.get("company_name", ""),
            stock_code=draft.get("stock_code", itask.stock_code),
            industry=draft.get("industry", ""),
            sub_industry=draft.get("sub_industry", ""),
            business_description=draft.get("business_description", ""),
            keywords=draft.get("keywords", []),
            competitors=draft.get("competitors", []),
            macro_factors=draft.get("macro_factors", []),
            monitoring_indicators=draft.get("monitoring_indicators", []),
            company_type=draft.get("company_type", ""),
            investment_strategy=draft.get("investment_strategy", "balanced"),
            analysis_dimensions=draft.get("analysis_dimensions", {}),
            is_active=auto_weekly,
        )
        itask.framework = framework
        itask.status = STATUS_STRATEGY_CONFIRMED

        # 后台启动 crawl → analyze → report
        thread = threading.Thread(target=self._run_from_crawl, args=(itask,), daemon=True)
        thread.start()
        return True

    def _prepare_interactive(self, itask: InteractiveTask) -> None:
        """后台获取公司信息 + AI 生成策略草案。"""
        try:
            # 获取公司概览
            quote_service = StockQuoteService()
            quote = quote_service.fetch_quote(itask.stock_code)

            financial_service = FinancialDataService()
            fin_summary = financial_service.fetch_summary(itask.stock_code)

            itask.company_info = {
                "code": quote.get("code", itask.stock_code),
                "name": quote.get("name", ""),
                "market": quote.get("market", ""),
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "market_cap": quote.get("market_cap"),
                "pe_ttm": quote.get("pe_ttm"),
                "pb": quote.get("pb"),
                "dividend_yield": quote.get("dividend_yield"),
                "week52_high": quote.get("week52_high"),
                "week52_low": quote.get("week52_low"),
                "financial_summary": fin_summary or "",
            }
            itask.status = STATUS_COMPANY_LOADED

            # AI 生成专业策略草案
            claude = ClaudeClient()
            framework_service = FrameworkService(claude)
            company_name = quote.get("name", itask.stock_code)
            framework = framework_service.build_framework_pro(company_name, investment_strategy=itask.investment_strategy)

            itask.strategy_draft = {
                "company_name": framework.company_name,
                "stock_code": framework.stock_code or itask.stock_code,
                "industry": framework.industry,
                "sub_industry": framework.sub_industry,
                "company_type": framework.company_type,
                "investment_strategy": framework.investment_strategy,
                "business_description": framework.business_description,
                "search_keywords": framework.keywords,
                "competitors": framework.competitors,
                "macro_factors": framework.macro_factors,
                "monitoring_indicators": framework.monitoring_indicators,
                "analysis_dimensions": framework.analysis_dimensions,
            }
            itask.status = STATUS_STRATEGY_PROPOSED

        except Exception as e:
            logger.error(f"交互式准备失败 [{itask.stock_code}]: {e}")
            itask.status = STATUS_ERROR
            itask.error = str(e)

    def _run_from_crawl(self, itask: InteractiveTask) -> None:
        """确认策略后，保存框架并执行 crawl → analyze → report。"""
        conn = init_db()
        try:
            framework_repo = FrameworkRepo(conn)
            framework_id = framework_repo.save(itask.framework)
            itask.framework.id = framework_id
            itask.framework_id = framework_id
            itask.status = STATUS_CRAWLING

            # 构造一个兼容的 ResearchTask 用于 SSE 推送
            compat_task = ResearchTask(
                task_id=itask.task_id,
                company_name=itask.framework.company_name,
                auto_weekly=itask.auto_weekly,
                queue=itask.queue,
            )
            claude = ClaudeClient()
            self._execute_from_crawl(compat_task, itask.framework, conn, claude)
            itask.status = STATUS_REPORT_DONE
            # 从最后一个事件中提取 report_id
            # report_id 已经通过 queue 推送了
        except Exception as e:
            logger.error(f"交互式流水线失败 [{itask.stock_code}]: {e}")
            itask.status = STATUS_ERROR
            itask.error = str(e)
            itask.queue.put(ProgressEvent(step=STEP_ERROR, message=str(e)))
        finally:
            conn.close()

    # ========== 共用：从 crawl 步骤开始执行 ==========

    def _execute_from_crawl(self, task: ResearchTask, framework: AnalysisFramework,
                            conn, claude: ClaudeClient) -> None:
        """执行 crawl → analyze → report（被全自动和交互模式共用）。"""
        news_repo = NewsRepo(conn)
        analysis_repo = AnalysisRepo(conn)
        report_repo = ReportRepo(conn)
        reflection_repo = ReflectionRepo(conn)

        # 步骤 1.5: 反思上期报告（对比评级 vs 实际涨跌）
        reflection_service = ReflectionService(claude, reflection_repo, report_repo)
        try:
            task.queue.put(ProgressEvent(
                step=STEP_ANALYZE,
                message="正在对比上期报告与实际表现...",
            ))
            reflection_service.check_and_reflect(framework)
        except Exception as e:
            logger.warning(f"反思阶段失败（不影响后续流程）: {e}")

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
        financial_raw = financial_service.fetch_summary(framework.stock_code)
        if financial_raw:
            task.queue.put(ProgressEvent(
                step=STEP_CRAWL_NEWS,
                message="财务数据获取完成",
            ))

        # 步骤 3: AI 分析（新闻 + 财报并行）
        task.queue.put(ProgressEvent(
            step=STEP_ANALYZE,
            message="正在进行 AI 分析...",
        ))

        # 3a: 财报 AI 分析
        financial_analysis_text = ""
        fa_result = {}
        if financial_raw and "获取失败" not in financial_raw:
            task.queue.put(ProgressEvent(
                step=STEP_ANALYZE,
                message="正在分析财报数据...",
            ))
            fa_service = FinancialAnalysisService(claude)
            fa_result = fa_service.analyze(framework, financial_raw)
            financial_analysis_text = fa_service.format_for_report(fa_result)
            task.queue.put(ProgressEvent(
                step=STEP_ANALYZE,
                message="财报分析完成",
            ))

        # 3b: 雪球观点 AI 分析
        xueqiu_analysis_text = ""
        xq_result = {}
        if framework.stock_code:
            task.queue.put(ProgressEvent(
                step=STEP_ANALYZE,
                message="正在抓取雪球讨论...",
            ))
            xq_service = XueqiuOpinionService(claude)
            xq_result = xq_service.analyze(framework)
            xueqiu_analysis_text = xq_service.format_for_report(xq_result)
            if xueqiu_analysis_text:
                task.queue.put(ProgressEvent(
                    step=STEP_ANALYZE,
                    message="雪球观点分析完成",
                ))

        # 3c: 新闻 AI 分析
        analysis_service = AnalysisService(claude, news_repo, analysis_repo)
        analysis = analysis_service.analyze_week(framework)

        task.queue.put(ProgressEvent(
            step=STEP_ANALYZE,
            message=f"新闻分析完成，处理了 {len(analysis.news_analyses)} 条新闻",
        ))

        # 3d: 技术面分析
        technical_analysis_text = ""
        technical_detail = {}
        if framework.stock_code:
            task.queue.put(ProgressEvent(
                step=STEP_ANALYZE,
                message="正在分析技术面...",
            ))
            try:
                from datetime import date, timedelta
                history_service = StockHistoryService()
                end = date.today().strftime("%Y%m%d")
                start = (date.today() - timedelta(days=180)).strftime("%Y%m%d")
                history_data = history_service.fetch_history(framework.stock_code, start, end)
                if history_data.get("data") and not history_data.get("error"):
                    ta_service = TechnicalAnalysisService(claude)
                    ta_result = ta_service.analyze(framework, history_data)
                    technical_detail = ta_result
                    technical_analysis_text = ta_service.format_for_report(ta_result)
                    task.queue.put(ProgressEvent(
                        step=STEP_ANALYZE,
                        message="技术面分析完成",
                    ))
                else:
                    logger.warning(f"技术面分析跳过: 历史数据不可用 ({history_data.get('error', '')})")
            except Exception as e:
                logger.warning(f"技术面分析失败: {e}")

        # 收集各路标准化信号
        def _safe_extract(result: dict) -> AnalystSignal:
            """从分析结果 dict 提取标准化信号。"""
            signal = result.get("signal", "neutral")
            confidence = result.get("confidence", 0.0)
            if signal not in ("bullish", "bearish", "neutral"):
                # 兼容中文信号
                cn_map = {"看多": "bullish", "看空": "bearish", "中性": "neutral"}
                signal = cn_map.get(signal, "neutral")
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                cn_conf = {"高": 0.8, "中": 0.5, "低": 0.2}
                confidence = cn_conf.get(str(confidence), 0.0)
            return AnalystSignal(signal=signal, confidence=min(max(confidence, 0.0), 1.0))

        analyst_signals = AnalystSignals(
            news=AnalystSignal(signal=analysis.signal or "neutral", confidence=analysis.confidence) if analysis else AnalystSignal(),
            financial=_safe_extract(fa_result) if fa_result else AnalystSignal(),
            sentiment=_safe_extract(xq_result) if xq_result else AnalystSignal(),
            technical=_safe_extract(technical_detail) if technical_detail else AnalystSignal(),
        )

        # 检索各角色历史教训
        bull_memory = reflection_service.get_memories_for_role(framework, "bull")
        bear_memory = reflection_service.get_memories_for_role(framework, "bear")
        advisor_memory = reflection_service.get_memories_for_role(framework, "risk_advisor")

        # 3e: Bull/Bear 辩论（注入历史教训）
        debate_text = ""
        debate_detail = {}
        news_summary_text = analysis.weekly_summary if analysis else ""
        task.queue.put(ProgressEvent(
            step=STEP_ANALYZE,
            message="看多研究员分析中...",
        ))
        try:
            debate_service = DebateService(claude)
            debate_result = debate_service.debate(
                framework,
                financial_context=financial_analysis_text,
                xueqiu_context=xueqiu_analysis_text,
                news_summary=news_summary_text,
                technical_context=technical_analysis_text,
                bull_memory=bull_memory,
                bear_memory=bear_memory,
            )
            debate_detail = debate_result
            debate_text = debate_service.format_for_report(debate_result)
            task.queue.put(ProgressEvent(
                step=STEP_ANALYZE,
                message="Bull/Bear 辩论完成",
            ))
        except Exception as e:
            logger.warning(f"Bull/Bear 辩论失败: {e}")

        # 辩论信号
        if debate_detail:
            analyst_signals.debate = _safe_extract(debate_detail)

        # 步骤 4: 生成报告（传入五路分析结论 + 历史教训）
        task.queue.put(ProgressEvent(
            step=STEP_GENERATE_REPORT,
            message="正在生成投资报告...",
        ))

        report_service = ReportService(claude, analysis_repo, report_repo, news_repo)
        report = report_service.generate_report(
            framework,
            financial_context=financial_analysis_text,
            xueqiu_context=xueqiu_analysis_text,
            debate_context=debate_text,
            technical_context=technical_analysis_text,
            memory_context=advisor_memory,
            debate_detail=debate_detail,
            technical_detail=technical_detail,
            financial_detail=financial_analysis_text,
            news_detail=news_summary_text,
            xueqiu_detail=xueqiu_analysis_text,
            analyst_signals=analyst_signals,
        )
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
