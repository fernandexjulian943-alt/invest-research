import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.services.financial_service import FinancialDataService
from invest_research.services.stock_quote_service import StockQuoteService
from invest_research.services.stock_history_service import StockHistoryService
from invest_research.services.dividend_service import DividendService
from invest_research.services.market_utils import detect_market, normalize_stock_code, search_stock_by_name
from invest_research.services.xueqiu_analysis import fetch_xueqiu_posts
from invest_research.services.research_pipeline import (
    ResearchPipeline, STEP_DONE, STEP_ERROR,
    STATUS_COMPANY_LOADED, STATUS_STRATEGY_PROPOSED, STATUS_ERROR,
)
from invest_research.services.chat_service import ChatService

logger = logging.getLogger(__name__)

app = FastAPI(title="AI 投研分析系统")
pipeline = ResearchPipeline()
chat_service = ChatService()

STATIC_DIR = Path(__file__).parent.parent / "static"


class ResearchRequest(BaseModel):
    company_name: str
    auto_weekly: bool = False


class InteractiveResearchRequest(BaseModel):
    stock_code: str
    investment_strategy: str = "balanced"


class ConfirmStrategyRequest(BaseModel):
    edits: dict = {}
    auto_weekly: bool = False


class ResearchResponse(BaseModel):
    task_id: str


class ChatSessionRequest(BaseModel):
    framework_id: int
    model_provider: str = "deepseek"


class ChatMessageRequest(BaseModel):
    message: str


class ChatProviderRequest(BaseModel):
    provider: str


class ChatRefreshDataRequest(BaseModel):
    action: str  # "refresh_financial" | "regenerate_report"


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = STATIC_DIR / "index.html"
    return index_path.read_text(encoding="utf-8")


@app.get("/api/reports")
async def list_reports():
    """按公司分组返回所有报告摘要。"""
    conn = init_db()
    try:
        framework_repo = FrameworkRepo(conn)
        report_repo = ReportRepo(conn)

        frameworks = framework_repo.list_all()
        result = []
        for fw in frameworks:
            reports = report_repo.get_by_framework(fw.id, limit=50)
            if not reports:
                continue
            result.append({
                "company_name": fw.company_name,
                "industry": fw.industry,
                "sub_industry": fw.sub_industry,
                "framework_id": fw.id,
                "reports": [
                    {
                        "id": r.id,
                        "report_date": r.report_date.isoformat() if r.report_date else "",
                        "investment_rating": r.investment_rating,
                        "executive_summary": r.executive_summary,
                    }
                    for r in reports
                ],
            })
        return result
    finally:
        conn.close()


@app.get("/api/reports/{report_id}")
async def get_report(report_id: int):
    """返回单份报告完整内容。"""
    conn = init_db()
    try:
        report_repo = ReportRepo(conn)
        report = report_repo.get_by_id(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")

        framework_repo = FrameworkRepo(conn)
        framework = framework_repo.get_by_id(report.framework_id)

        return {
            "id": report.id,
            "company_name": framework.company_name if framework else "",
            "stock_code": framework.stock_code if framework else "",
            "industry": framework.industry if framework else "",
            "report_date": report.report_date.isoformat() if report.report_date else "",
            "investment_rating": report.investment_rating,
            "rating_rationale": report.rating_rationale,
            "executive_summary": report.executive_summary,
            "detailed_analysis": report.detailed_analysis,
            "previous_rating": report.previous_rating,
            "rating_change_reason": report.rating_change_reason,
            "changes_from_previous": report.changes_from_previous,
            "signal_summary": report.signal_summary.model_dump() if report.signal_summary else None,
            "debate_detail": report.debate_detail or None,
            "technical_detail": report.technical_detail or None,
            "financial_detail": report.financial_detail or None,
            "news_detail": report.news_detail or None,
            "xueqiu_detail": report.xueqiu_detail or None,
            "risks": [r.model_dump() for r in report.risks],
            "opportunities": [o.model_dump() for o in report.opportunities],
        }
    finally:
        conn.close()


@app.get("/api/frameworks")
async def list_frameworks():
    """返回所有框架列表，含最新两期评级。"""
    conn = init_db()
    try:
        repo = FrameworkRepo(conn)
        report_repo = ReportRepo(conn)
        frameworks = repo.list_all()
        result = []
        for fw in frameworks:
            recent = report_repo.get_by_framework(fw.id, limit=2)
            latest_rating = recent[0].investment_rating if recent else ""
            prev_rating = recent[1].investment_rating if len(recent) > 1 else ""
            result.append({
                "id": fw.id,
                "company_name": fw.company_name,
                "stock_code": fw.stock_code,
                "industry": fw.industry,
                "sub_industry": fw.sub_industry,
                "is_active": fw.is_active,
                "latest_rating": latest_rating,
                "previous_rating": prev_rating,
                "created_at": str(fw.created_at) if fw.created_at else "",
            })
        return result
    finally:
        conn.close()


@app.get("/api/frameworks/{framework_id}/reports")
async def list_framework_reports(framework_id: int):
    """返回某个框架的所有报告摘要（轻量，用于日期导航）。"""
    conn = init_db()
    try:
        report_repo = ReportRepo(conn)
        reports = report_repo.get_by_framework(framework_id, limit=100)
        return [
            {
                "id": r.id,
                "report_date": r.report_date.isoformat() if r.report_date else "",
                "investment_rating": r.investment_rating,
            }
            for r in reports
        ]
    finally:
        conn.close()


@app.delete("/api/frameworks/{framework_id}")
async def delete_framework(framework_id: int):
    """删除（停用）框架。"""
    conn = init_db()
    try:
        repo = FrameworkRepo(conn)
        framework = repo.get_by_id(framework_id)
        if not framework:
            raise HTTPException(status_code=404, detail="框架不存在")
        framework.is_active = False
        repo.update(framework)
        return {"ok": True}
    finally:
        conn.close()


@app.put("/api/frameworks/{framework_id}/activate")
async def activate_framework(framework_id: int):
    """启用框架。"""
    conn = init_db()
    try:
        repo = FrameworkRepo(conn)
        framework = repo.get_by_id(framework_id)
        if not framework:
            raise HTTPException(status_code=404, detail="框架不存在")
        framework.is_active = True
        repo.update(framework)
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/frameworks/{framework_id}/financial")
def get_framework_financial(framework_id: int, refresh: bool = False):
    """获取框架对应股票的财报分析数据。

    默认返回数据库缓存；传 ?refresh=true 则强制从网络重新拉取并更新缓存。
    """
    conn = init_db()
    try:
        repo = FrameworkRepo(conn)
        framework = repo.get_by_id(framework_id)
        if not framework:
            raise HTTPException(status_code=404, detail="框架不存在")

        if not framework.stock_code:
            return {
                "stock_code": "",
                "company_name": framework.company_name,
                "summary": "",
                "fetched_at": None,
                "from_cache": False,
                "error": "该股票未设置股票代码",
            }

        # 有缓存且不强制刷新 → 直接返回缓存
        if not refresh and framework.financial_summary:
            return {
                "stock_code": framework.stock_code,
                "company_name": framework.company_name,
                "summary": framework.financial_summary,
                "fetched_at": str(framework.financial_fetched_at) if framework.financial_fetched_at else None,
                "from_cache": True,
                "error": "",
            }

        # 从网络拉取最新财报
        service = FinancialDataService()
        summary = service.fetch_summary(framework.stock_code)

        # 拉取成功则写入缓存
        if summary:
            repo.save_financial_cache(framework_id, summary)

        return {
            "stock_code": framework.stock_code,
            "company_name": framework.company_name,
            "summary": summary,
            "fetched_at": None,
            "from_cache": False,
            "error": "" if summary else "无法获取该股票的财务数据，请检查股票代码是否正确",
        }
    finally:
        conn.close()


# ========== 交互式研究 ==========


@app.post("/api/research/interactive", response_model=ResearchResponse)
async def start_interactive_research(req: InteractiveResearchRequest):
    """创建交互式研究任务。后台自动获取公司信息 + 生成策略草案。"""
    resolved = _resolve_stock_code(req.stock_code)
    if not resolved:
        raise HTTPException(status_code=400, detail=f"无法识别股票: {req.stock_code}")
    task_id = uuid.uuid4().hex[:12]
    pipeline.create_interactive(task_id, resolved, req.investment_strategy)
    return ResearchResponse(task_id=task_id)


@app.get("/api/research/{task_id}/status")
async def get_research_status(task_id: str):
    """获取交互式任务的当前状态和数据。"""
    itask = pipeline.get_interactive_task(task_id)
    if not itask:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = {
        "task_id": itask.task_id,
        "status": itask.status,
        "stock_code": itask.stock_code,
    }
    if itask.company_info:
        result["company_info"] = itask.company_info
    if itask.strategy_draft:
        result["strategy_draft"] = itask.strategy_draft
    if itask.error:
        result["error"] = itask.error
    if itask.report_id is not None:
        result["report_id"] = itask.report_id
    return result


@app.post("/api/research/{task_id}/confirm-strategy")
async def confirm_strategy(task_id: str, req: ConfirmStrategyRequest):
    """用户确认/修改策略，触发后续自动流程。"""
    itask = pipeline.get_interactive_task(task_id)
    if not itask:
        raise HTTPException(status_code=404, detail="任务不存在")
    if itask.status != STATUS_STRATEGY_PROPOSED:
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {itask.status} 不允许确认策略（需要 strategy_proposed）",
        )
    ok = pipeline.confirm_strategy(task_id, req.edits, req.auto_weekly)
    if not ok:
        raise HTTPException(status_code=500, detail="确认策略失败")
    return {"ok": True, "message": "策略已确认，正在启动分析流程..."}


# ========== 原有全自动模式 ==========


@app.post("/api/research", response_model=ResearchResponse)
async def start_research(req: ResearchRequest):
    """启动新研究，返回 task_id。"""
    task_id = uuid.uuid4().hex[:12]
    pipeline.start(task_id, req.company_name, req.auto_weekly)
    return ResearchResponse(task_id=task_id)


@app.get("/api/research/{task_id}/events")
async def research_events(task_id: str):
    """SSE 端点，推送研究进度（兼容全自动和交互式任务）。"""
    # 优先查全自动任务，再查交互式任务
    task = pipeline.get_task(task_id)
    queue = task.queue if task else None
    if not queue:
        itask = pipeline.get_interactive_task(task_id)
        if itask:
            queue = itask.queue
    if not queue:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, queue.get, True, 30.0
                )
                data = {
                    "step": event.step,
                    "message": event.message,
                }
                if event.report_id is not None:
                    data["report_id"] = event.report_id
                if event.articles is not None:
                    data["articles"] = event.articles
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if event.step in (STEP_DONE, STEP_ERROR):
                    break
            except Exception:
                # 队列超时，发送心跳保持连接
                yield f": heartbeat\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _resolve_stock_code(user_input: str) -> str:
    """将用户输入（代码或公司名称）解析为标准股票代码。

    解析顺序：标准代码检测 → 框架DB名称匹配 → AKShare名称搜索。
    返回标准化代码，失败返回空串。
    """
    cleaned = user_input.strip()
    if not cleaned:
        return ""

    # 1. 尝试作为股票代码识别
    code = normalize_stock_code(cleaned)
    if detect_market(code):
        return code

    # 2. 搜索已有框架数据库（按公司名称匹配）
    try:
        conn = init_db()
        try:
            repo = FrameworkRepo(conn)
            for fw in repo.list_all():
                if fw.company_name and cleaned in fw.company_name and fw.stock_code:
                    resolved = normalize_stock_code(fw.stock_code)
                    if detect_market(resolved):
                        return resolved
        finally:
            conn.close()
    except Exception:
        pass

    # 3. AKShare 名称搜索（A 股全量 + 美股/港股热门）
    found_code, found_market = search_stock_by_name(cleaned)
    if found_code:
        return found_code

    return ""


@app.get("/api/stock/quote")
def stock_quote(code: str = ""):
    """实时股票报价（支持股票代码或公司名称）。"""
    if not code.strip():
        raise HTTPException(status_code=400, detail="缺少 code 参数")
    resolved = _resolve_stock_code(code)
    if not resolved:
        return {"error": f"无法识别股票: {code}，请输入标准股票代码（如 600519、MSFT、00700）"}
    service = StockQuoteService()
    return service.fetch_quote(resolved)


@app.get("/api/stock/history")
def stock_history(
    code: str = "",
    start_date: str = "",
    end_date: str = "",
    period: str = "daily",
    adjust: str = "qfq",
):
    """历史股票价格查询（支持股票代码或公司名称）。"""
    if not code.strip():
        raise HTTPException(status_code=400, detail="缺少 code 参数")
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="缺少 start_date 或 end_date 参数")
    resolved = _resolve_stock_code(code)
    if not resolved:
        return {"error": f"无法识别股票: {code}，请输入标准股票代码（如 600519、MSFT、00700）"}
    service = StockHistoryService()
    return service.fetch_history(
        stock_code=resolved,
        start_date=start_date.strip(),
        end_date=end_date.strip(),
        period=period.strip(),
        adjust=adjust.strip(),
    )


@app.get("/api/stock/financial")
def stock_financial(code: str = ""):
    """公司财报研究（支持股票代码或公司名称）。"""
    if not code.strip():
        raise HTTPException(status_code=400, detail="缺少 code 参数")
    resolved = _resolve_stock_code(code)
    if not resolved:
        return {
            "stock_code": code.strip(),
            "summary": "",
            "error": f"无法识别股票: {code}，请输入标准股票代码（如 600519、MSFT、00700）",
        }
    service = FinancialDataService()
    summary = service.fetch_summary(resolved)
    return {
        "stock_code": resolved,
        "summary": summary,
        "error": "" if summary else "无法获取该股票的财务数据，请检查股票代码是否正确",
    }


@app.get("/api/stock/dividend")
def stock_dividend(code: str = ""):
    """股票分红查询（明细 + 累计分红 + 股息率趋势）。"""
    if not code.strip():
        raise HTTPException(status_code=400, detail="缺少 code 参数")
    resolved = _resolve_stock_code(code)
    if not resolved:
        return {
            "error": f"无法识别股票: {code}，请输入标准股票代码（如 600519、MSFT、00700）",
            "error_code": "NOT_FOUND",
            "suggestion": "请输入标准股票代码",
        }
    service = DividendService()
    return service.fetch_dividend(resolved)


@app.get("/api/stock/xueqiu-analysis")
def stock_xueqiu_analysis(code: str = ""):
    """雪球大V观点分析（Playwright 抓取股票讨论页）。"""
    if not code.strip():
        raise HTTPException(status_code=400, detail="缺少 code 参数")
    resolved = _resolve_stock_code(code)
    if not resolved:
        return {"stock_code": code.strip(), "symbol": "", "posts": [], "error": f"无法识别股票: {code}"}
    return fetch_xueqiu_posts(resolved)


# ========== 对话系统 ==========


@app.get("/api/chat/recent-stocks")
async def get_recent_chat_stocks():
    """获取最近对话过的股票列表（按时间排序去重）。"""
    return chat_service.get_recent_stocks()


@app.post("/api/chat/sessions")
async def create_chat_session(req: ChatSessionRequest):
    """创建对话会话。"""
    session = chat_service.create_session(req.framework_id, req.model_provider)
    return {
        "session_id": session.id,
        "framework_id": session.framework_id,
        "model_provider": session.model_provider,
    }


@app.get("/api/chat/sessions/{session_id}")
async def get_chat_session(session_id: str):
    """获取对话历史。"""
    session = chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = chat_service.get_history(session_id)
    return {
        "session_id": session.id,
        "framework_id": session.framework_id,
        "model_provider": session.model_provider,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "specialist": m.specialist,
                "data_refs": m.data_refs,
                "created_at": str(m.created_at) if m.created_at else "",
            }
            for m in messages
        ],
    }


@app.get("/api/chat/frameworks/{framework_id}/sessions")
async def list_chat_sessions(framework_id: int):
    """列出某股票的所有对话会话。"""
    sessions = chat_service.list_sessions(framework_id)
    return [
        {
            "session_id": s.id,
            "framework_id": s.framework_id,
            "model_provider": s.model_provider,
            "created_at": str(s.created_at) if s.created_at else "",
            "updated_at": str(s.updated_at) if s.updated_at else "",
        }
        for s in sessions
    ]


@app.post("/api/chat/sessions/{session_id}/messages")
async def send_chat_message(session_id: str, req: ChatMessageRequest):
    """发送消息并获取流式响应（SSE）。"""
    session = chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def event_generator():
        for chunk in chat_service.chat_stream(session_id, req.message):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.put("/api/chat/sessions/{session_id}/provider")
async def update_chat_provider(session_id: str, req: ChatProviderRequest):
    """切换对话模型。"""
    if req.provider not in ("anthropic", "deepseek"):
        raise HTTPException(status_code=400, detail="provider 只支持 anthropic 或 deepseek")
    chat_service.update_provider(session_id, req.provider)
    return {"ok": True, "provider": req.provider}


@app.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """删除对话会话。"""
    chat_service.delete_session(session_id)
    return {"ok": True}


@app.post("/api/chat/sessions/{session_id}/refresh-data")
async def refresh_chat_data(session_id: str, req: ChatRefreshDataRequest):
    """刷新对话中的数据（财务刷新 / 触发重新研究）。"""
    session = chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    conn = init_db()
    try:
        fw = FrameworkRepo(conn).get_by_id(session.framework_id)
        if not fw:
            raise HTTPException(status_code=404, detail="股票不存在")
    finally:
        conn.close()

    if req.action == "refresh_financial":
        svc = FinancialDataService()
        summary = svc.fetch_summary(fw.stock_code)
        if summary:
            conn = init_db()
            try:
                FrameworkRepo(conn).save_financial_cache(fw.id, summary)
            finally:
                conn.close()
            return {"ok": True, "action": "refresh_financial", "message": "财报数据已刷新"}
        return {"ok": False, "action": "refresh_financial", "message": "财报数据获取失败"}

    elif req.action == "regenerate_report":
        task_id = str(uuid.uuid4())[:8]
        asyncio.get_event_loop().run_in_executor(
            None, pipeline.start, task_id, fw.company_name, False,
        )
        return {"ok": True, "action": "regenerate_report", "task_id": task_id,
                "message": "研究已启动，请等待完成"}

    raise HTTPException(status_code=400, detail=f"未知操作: {req.action}")


@app.post("/api/chat/sessions/{session_id}/re-research")
async def trigger_chat_reresearch(session_id: str):
    """从对话中触发重新研究。"""
    session = chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    conn = init_db()
    try:
        fw = FrameworkRepo(conn).get_by_id(session.framework_id)
        if not fw:
            raise HTTPException(status_code=404, detail="股票不存在")
    finally:
        conn.close()

    task_id = str(uuid.uuid4())[:8]
    asyncio.get_event_loop().run_in_executor(
        None, pipeline.start, task_id, fw.company_name, False,
    )
    return {"ok": True, "task_id": task_id, "company_name": fw.company_name}


@app.get("/api/chat/sessions/{session_id}/export")
async def export_chat_session(session_id: str):
    """导出对话为 Markdown 文件。"""
    from fastapi.responses import Response

    content = chat_service.export_session(session_id)
    if content is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 文件名用 URL 编码处理中文
    from urllib.parse import quote
    first_line = content.split("\n", 1)[0]
    filename = first_line.replace("# ", "").replace(" ", "_") + ".md"
    encoded_filename = quote(filename)

    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


def create_app() -> FastAPI:
    return app
