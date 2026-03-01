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
from invest_research.services.research_pipeline import ResearchPipeline, STEP_DONE, STEP_ERROR

logger = logging.getLogger(__name__)

app = FastAPI(title="AI 投研分析系统")
pipeline = ResearchPipeline()

STATIC_DIR = Path(__file__).parent.parent / "static"


class ResearchRequest(BaseModel):
    company_name: str
    auto_weekly: bool = False


class ResearchResponse(BaseModel):
    task_id: str


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
            "industry": framework.industry if framework else "",
            "report_date": report.report_date.isoformat() if report.report_date else "",
            "investment_rating": report.investment_rating,
            "rating_rationale": report.rating_rationale,
            "executive_summary": report.executive_summary,
            "detailed_analysis": report.detailed_analysis,
            "previous_rating": report.previous_rating,
            "rating_change_reason": report.rating_change_reason,
            "changes_from_previous": report.changes_from_previous,
            "risks": [r.model_dump() for r in report.risks],
            "opportunities": [o.model_dump() for o in report.opportunities],
        }
    finally:
        conn.close()


@app.get("/api/frameworks")
async def list_frameworks():
    """返回所有框架列表。"""
    conn = init_db()
    try:
        repo = FrameworkRepo(conn)
        frameworks = repo.list_all()
        return [
            {
                "id": fw.id,
                "company_name": fw.company_name,
                "stock_code": fw.stock_code,
                "industry": fw.industry,
                "sub_industry": fw.sub_industry,
                "is_active": fw.is_active,
                "created_at": str(fw.created_at) if fw.created_at else "",
            }
            for fw in frameworks
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
def get_framework_financial(framework_id: int):
    """获取框架对应股票的基础财报分析数据。"""
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
                "error": "该股票未设置股票代码",
            }

        service = FinancialDataService()
        summary = service.fetch_summary(framework.stock_code)

        return {
            "stock_code": framework.stock_code,
            "company_name": framework.company_name,
            "summary": summary,
            "error": "" if summary else "无法获取该股票的财务数据，请检查股票代码是否正确",
        }
    finally:
        conn.close()


@app.post("/api/research", response_model=ResearchResponse)
async def start_research(req: ResearchRequest):
    """启动新研究，返回 task_id。"""
    task_id = uuid.uuid4().hex[:12]
    pipeline.start(task_id, req.company_name, req.auto_weekly)
    return ResearchResponse(task_id=task_id)


@app.get("/api/research/{task_id}/events")
async def research_events(task_id: str):
    """SSE 端点，推送研究进度。"""
    task = pipeline.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, task.queue.get, True, 30.0
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


def create_app() -> FastAPI:
    return app
