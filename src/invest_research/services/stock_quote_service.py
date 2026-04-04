"""实时股票报价服务，支持雪球（主）+ 新浪（备用）。"""

import logging
from datetime import datetime

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
        优先使用雪球，若失败则尝试新浪。
        """
        code = normalize_stock_code(stock_code)
        if not code:
            return {"error": "股票代码不能为空"}

        market = detect_market(code)
        if not market:
            return {"error": f"无法识别股票代码市场类型: {stock_code}"}

        # 优先尝试雪球
        try:
            return self._fetch_from_xueqiu(code, market)
        except Exception as exc:
            logger.warning("雪球接口失败，尝试备用源: %s", exc)

        # 备用：新浪财经（港股/A股）
        try:
            return self._fetch_from_sina(code, market)
        except Exception as exc:
            logger.warning("新浪接口也失败: %s", exc)

        # 美股特殊处理：需要代理
        if market == "US":
            return {
                "error": "美股数据源暂时不可用（需要代理）",
                "error_code": "MARKET_UNAVAILABLE",
                "suggestion": "配置代理后可恢复",
                "market": "US",
                "code": code,
            }

        return {
            "error": "获取行情数据失败",
            "error_code": "SERVICE_ERROR",
            "suggestion": "数据源暂时不可用，请稍后重试",
        }

    def _fetch_from_xueqiu(self, code: str, market: str) -> dict:
        """从雪球获取行情。"""
        try:
            from invest_research.services.xq_token_manager import call_xq_api

            xq_symbol = build_xq_symbol(code, market)
            df = call_xq_api(xq_symbol)

            if df is None or df.empty:
                raise ValueError(f"未获取到 {code} 的行情数据")

            return self._parse_quote(df, code, market)
        except KeyError as exc:
            if "data" in str(exc):
                raise Exception("雪球token过期") from exc
            raise

    def _fetch_from_sina(self, code: str, market: str) -> dict:
        """从新浪财经获取行情（港股备用）。"""
        import requests

        if market == "HK":
            # 新浪港股: rt_hk00XXX
            symbol = f"rt_hk{code}"
        elif market == "A":
            # 新浪A股: sz000001 / sh600519
            if code.startswith("6"):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"
        elif market == "US":
            # 新浪美股: nvda
            symbol = code.lower()
        else:
            raise ValueError(f"不支持的市场: {market}")

        url = f"https://hq.sinajs.cn/list={symbol}"
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        }

        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        text = resp.text.strip()
        if not text or "=" not in text:
            raise ValueError(f"新浪返回空数据: {text}")

        # 解析: var hq_str_rt_hk00700="TENCENT,腾讯控股,..."
        data_part = text.split("=")[1].strip('"')
        parts = data_part.split(",")

        if len(parts) < 10:
            raise ValueError(f"新浪数据格式异常: {parts}")

        if market == "HK":
            return self._parse_sina_hk(parts, code)
        elif market == "A":
            return self._parse_sina_a(parts, code)
        else:
            return self._parse_sina_us(parts, code)

    def _parse_sina_hk(self, parts: list, code: str) -> dict:
        """解析新浪港股数据。"""
        # 格式: name,现价,开盘,最高,最低,昨收,涨跌,涨跌幅,...
        name = parts[1]
        prev_close = float(parts[5]) if parts[5] else None
        price = float(parts[2]) if parts[2] else prev_close
        change = float(parts[6]) if parts[6] else None
        change_pct = float(parts[7]) if parts[7] else None
        high = float(parts[3]) if parts[3] else None
        low = float(parts[4]) if parts[4] else None
        open_price = float(parts[2]) if parts[2] else None

        return {
            "market": "HK",
            "code": code,
            "name": name,
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "open": open_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": None,
            "amount": None,
            "pe_ttm": None,
            "pb": None,
            "market_cap": None,
            "dividend_yield": None,
            "week52_high": None,
            "week52_low": None,
            "currency": "HKD",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": "",
        }

    def _parse_sina_a(self, parts: list, code: str) -> dict:
        """解析新浪A股数据。"""
        name = parts[0]
        open_price = float(parts[1]) if parts[1] else None
        prev_close = float(parts[2]) if parts[2] else None
        price = float(parts[3]) if parts[3] else None
        high = float(parts[4]) if parts[4] else None
        low = float(parts[5]) if parts[5] else None
        # parts[6] 买入价
        # parts[7] 卖出价
        volume = int(float(parts[8]) * 100) if parts[8] else None  # 手转股
        amount = float(parts[9]) if parts[9] else None
        # parts[10-13] 买卖盘数据

        return {
            "market": "A",
            "code": code,
            "name": name,
            "price": price,
            "change": price - prev_close if price and prev_close else None,
            "change_pct": ((price - prev_close) / prev_close * 100) if price and prev_close else None,
            "open": open_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": volume,
            "amount": amount,
            "pe_ttm": None,
            "pb": None,
            "market_cap": None,
            "dividend_yield": None,
            "week52_high": None,
            "week52_low": None,
            "currency": "CNY",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": "",
        }

    def _parse_sina_us(self, parts: list, code: str) -> dict:
        """解析新浪美股数据。"""
        name = parts[0]
        open_price = float(parts[1]) if parts[1] else None
        prev_close = float(parts[2]) if parts[2] else None
        price = float(parts[3]) if parts[3] else None
        high = float(parts[4]) if parts[4] else None
        low = float(parts[5]) if parts[5] else None
        volume = int(float(parts[7])) if parts[7] else None

        return {
            "market": "US",
            "code": code,
            "name": name,
            "price": price,
            "change": price - prev_close if price and prev_close else None,
            "change_pct": ((price - prev_close) / prev_close * 100) if price and prev_close else None,
            "open": open_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": volume,
            "amount": None,
            "pe_ttm": None,
            "pb": None,
            "market_cap": None,
            "dividend_yield": None,
            "week52_high": None,
            "week52_low": None,
            "currency": "USD",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": "",
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
