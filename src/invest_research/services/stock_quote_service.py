"""实时股票报价服务，基于 AKShare 雪球接口。"""

import logging

from invest_research.services.market_utils import (
    build_xq_symbol,
    detect_market,
    normalize_stock_code,
)

logger = logging.getLogger(__name__)


class StockQuoteService:
    """获取实时股票行情数据。"""

    def fetch_quote(self, stock_code: str) -> dict:
        """查询实时行情，返回结构化字典。

        支持 A股（600519）、美股（MSFT）、港股（00700）。
        """
        code = normalize_stock_code(stock_code)
        if not code:
            return {"error": "股票代码不能为空"}

        market = detect_market(code)
        if not market:
            return {"error": f"无法识别股票代码市场类型: {stock_code}"}

        try:
            from invest_research.services.xq_token_manager import call_xq_api

            xq_symbol = build_xq_symbol(code, market)
            df = call_xq_api(xq_symbol)

            if df is None or df.empty:
                return {
                    "error": f"未获取到 {stock_code} 的行情数据",
                    "error_code": "NOT_FOUND",
                    "suggestion": "请检查股票代码是否正确，或稍后重试",
                }

            return self._parse_quote(df, code, market)
        except Exception as exc:
            logger.warning("获取实时行情失败 [%s]: %s", stock_code, exc, exc_info=True)
            return {
                "error": f"获取行情数据失败: {exc}",
                "error_code": "SERVICE_ERROR",
                "suggestion": "数据源可能暂时不可用，请稍后重试",
            }

    @staticmethod
    def _parse_quote(df, code: str, market: str) -> dict:
        """将雪球接口返回的 DataFrame 解析为标准字典。"""
        data = {}
        for _, row in df.iterrows():
            item_name = str(row.get("item", ""))
            value = row.get("value")
            data[item_name] = value

        currency_map = {"A": "CNY", "HK": "HKD", "US": "USD"}
        currency = data.get("货币", currency_map.get(market, ""))

        return {
            "market": market,
            "code": code,
            "name": data.get("名称", ""),
            "price": _safe_float(data.get("现价")),
            "change": _safe_float(data.get("涨跌")),
            "change_pct": _safe_float(data.get("涨幅")),
            "open": _safe_float(data.get("今开")),
            "high": _safe_float(data.get("最高")),
            "low": _safe_float(data.get("最低")),
            "prev_close": _safe_float(data.get("昨收")),
            "volume": _safe_float(data.get("成交量")),
            "amount": _safe_float(data.get("成交额")),
            "pe_ttm": _safe_float(data.get("市盈率(TTM)")),
            "pb": _safe_float(data.get("市净率")),
            "market_cap": _safe_float(data.get("资产净值/总市值")),
            "dividend_yield": _safe_float(data.get("股息率(TTM)")),
            "week52_high": _safe_float(data.get("52周最高")),
            "week52_low": _safe_float(data.get("52周最低")),
            "currency": currency,
            "timestamp": data.get("时间", ""),
            "error": "",
        }


def _safe_float(value) -> float | None:
    """安全转换为 float，失败或 NaN/Inf 返回 None。"""
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
