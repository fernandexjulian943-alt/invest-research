"""股票分红查询服务：明细 + 累计分红 + 股息率趋势。"""

import logging

from invest_research.services.akshare_utils import AKShareError, call_akshare
from invest_research.services.market_utils import detect_market, normalize_stock_code

logger = logging.getLogger(__name__)


class DividendService:
    """获取股票分红数据。"""

    def fetch_dividend(self, stock_code: str) -> dict:
        """查询分红信息，返回明细 + 汇总 + 股息率趋势。"""
        code = normalize_stock_code(stock_code)
        if not code:
            return {"error": "股票代码不能为空", "error_code": "BAD_REQUEST", "suggestion": "请输入股票代码"}

        market = detect_market(code)
        if not market:
            return {
                "error": f"无法识别股票代码市场类型: {stock_code}",
                "error_code": "NOT_FOUND",
                "suggestion": "请输入标准股票代码（如 600519、MSFT、00700）",
            }

        try:
            import akshare as ak

            if market == "A":
                return self._fetch_a_share(ak, code)
            elif market == "HK":
                return self._fetch_hk(ak, code)
            elif market == "US":
                return self._fetch_us(ak, code)
            else:
                return {"error": f"不支持的市场类型: {market}", "error_code": "NOT_FOUND", "suggestion": ""}
        except AKShareError as e:
            return e.to_dict()
        except Exception as exc:
            logger.warning("获取分红数据失败 [%s]: %s", stock_code, exc, exc_info=True)
            return {"error": f"获取分红数据失败: {exc}", "error_code": "SERVICE_ERROR", "suggestion": "请稍后重试"}

    def _fetch_a_share(self, ak, code: str) -> dict:
        """A 股分红：ak.stock_history_dividend_detail(symbol, indicator='分红')"""
        df = call_akshare(ak.stock_history_dividend_detail, symbol=code, indicator="分红")

        if df is None or df.empty:
            return self._empty_result(code, "A", "该股票暂无分红记录")

        dividends = []
        for _, row in df.iterrows():
            dividends.append({
                "announce_date": _safe_str(row.get("公告日期")),
                "bonus_shares": _safe_float(row.get("送股", row.get("送股(股)"))),
                "transfer_shares": _safe_float(row.get("转增", row.get("转增(股)"))),
                "cash_per_share": _safe_float(row.get("派息", row.get("派息(税前)(元)"))),
                "ex_date": _safe_str(row.get("除权除息日")),
                "record_date": _safe_str(row.get("股权登记日")),
                "status": _safe_str(row.get("进度")),
            })

        return self._build_result(code, "A", dividends)

    def _fetch_hk(self, ak, code: str) -> dict:
        """港股分红：ak.stock_hk_dividend_payout_em(symbol)"""
        df = call_akshare(ak.stock_hk_dividend_payout_em, symbol=code)

        if df is None or df.empty:
            return self._empty_result(code, "HK", "该股票暂无分红记录")

        dividends = []
        for _, row in df.iterrows():
            # 从"每股派港币4.5元"格式中提取金额
            plan = str(row.get("分红方案", ""))
            cash = _parse_hk_dividend_plan(plan)
            dividends.append({
                "announce_date": _safe_str(row.get("最新公告日期")),
                "fiscal_year": _safe_str(row.get("财政年度")),
                "cash_per_share": cash,
                "dividend_plan": plan,
                "ex_date": _safe_str(row.get("除净日")),
                "record_date": _safe_str(row.get("截至过户日")),
                "distribution_type": _safe_str(row.get("分配类型")),
                "status": "已实施",
                "bonus_shares": 0,
                "transfer_shares": 0,
            })

        return self._build_result(code, "HK", dividends)

    def _fetch_us(self, ak, code: str) -> dict:
        """美股：AKShare 无直接分红接口，从基本信息提取股息率。"""
        try:
            from invest_research.services.xq_token_manager import call_xq_api
            df = call_xq_api(code)
            if df is None or df.empty:
                return self._empty_result(code, "US", "未获取到数据")

            data = {}
            for _, row in df.iterrows():
                item = str(row.get("item", ""))
                data[item] = row.get("value")

            dividend_yield = _safe_float(data.get("股息率(TTM)"))
            price = _safe_float(data.get("现价"))

            # 美股无历史分红明细，返回当前股息率信息
            result = {
                "stock_code": code,
                "market": "US",
                "dividends": [],
                "summary": {
                    "total_cash_per_share": None,
                    "total_count": 0,
                    "avg_annual_cash": None,
                    "note": "美股暂不支持历史分红明细，仅提供当前股息率",
                },
                "yield_trend": [],
                "current_dividend_yield": dividend_yield,
                "current_price": price,
                "error": "",
            }
            return result
        except Exception as exc:
            logger.warning("获取美股分红信息失败 [%s]: %s", code, exc)
            return self._empty_result(code, "US", f"获取失败: {exc}")

    @staticmethod
    def _build_result(code: str, market: str, dividends: list) -> dict:
        """构建完整返回结构：明细 + 汇总 + 股息率趋势。"""
        # 汇总统计
        cash_values = [d["cash_per_share"] for d in dividends if d.get("cash_per_share")]
        total_cash = sum(cash_values)
        total_count = len(dividends)

        # 按年分组计算股息率趋势
        year_cash: dict[str, float] = {}
        for d in dividends:
            # 优先用 fiscal_year（港股），再用 ex_date/announce_date
            date_str = d.get("fiscal_year") or d.get("ex_date") or d.get("announce_date") or ""
            if not date_str or date_str == "None":
                continue
            year = str(date_str)[:4]
            if year and year.isdigit():
                year_cash[year] = year_cash.get(year, 0) + (d.get("cash_per_share") or 0)

        years = sorted(year_cash.keys(), reverse=True)
        num_years = len(years)
        avg_annual = total_cash / num_years if num_years > 0 else 0

        yield_trend = [
            {"year": y, "cash_per_share": round(year_cash[y], 4)}
            for y in years
        ]

        return {
            "stock_code": code,
            "market": market,
            "dividends": dividends,
            "summary": {
                "total_cash_per_share": round(total_cash, 4),
                "total_count": total_count,
                "avg_annual_cash": round(avg_annual, 4),
                "years_covered": num_years,
            },
            "yield_trend": yield_trend,
            "error": "",
        }

    @staticmethod
    def _empty_result(code: str, market: str, message: str) -> dict:
        return {
            "stock_code": code,
            "market": market,
            "dividends": [],
            "summary": {"total_cash_per_share": 0, "total_count": 0, "avg_annual_cash": 0},
            "yield_trend": [],
            "error": message,
        }


def _parse_hk_dividend_plan(plan: str) -> float | None:
    """从港股分红方案文本中提取每股派息金额。

    例如: "每股派港币4.5元" → 4.5, "每股派0.35美元" → 0.35
    """
    import re
    if not plan:
        return None
    # 匹配数字（含小数）
    match = re.search(r"(\d+\.?\d*)", plan)
    if match:
        return float(match.group(1))
    return None


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        import math
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


def _safe_str(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s in ("None", "NaT", "nan"):
        return ""
    # 处理 Timestamp 对象
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return s.split(" ")[0]  # 去掉时间部分
