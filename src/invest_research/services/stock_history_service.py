"""历史股票价格查询服务，根据市场类型调用对应 AKShare API。"""

import logging
import math

from invest_research.services.market_utils import (
    detect_market,
    normalize_stock_code,
)

logger = logging.getLogger(__name__)

# 美股交易所 -> 东方财富前缀映射
US_EXCHANGE_PREFIX = {"NASDAQ": "105", "NYSE": "106", "AMEX": "107"}

# 进程级缓存，避免重复查询交易所前缀
_us_prefix_cache: dict[str, str] = {}


class StockHistoryService:
    """获取股票历史价格数据。"""

    def fetch_history(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        period: str = "daily",
        adjust: str = "qfq",
    ) -> dict:
        """查询历史价格。

        参数:
            stock_code: 股票代码（600519 / MSFT / 00700）
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD
            period: 周期 daily/weekly/monthly
            adjust: 复权 qfq(前复权)/hfq(后复权)/空串(不复权)

        返回:
            { market, code, period, adjust, data: [...], error }
        """
        code = normalize_stock_code(stock_code)
        if not code:
            return {"error": "股票代码不能为空"}

        market = detect_market(code)
        if not market:
            return {"error": f"无法识别股票代码市场类型: {stock_code}"}

        try:
            import akshare as ak

            if market == "A":
                return self._fetch_a_share(ak, code, start_date, end_date, period, adjust)
            elif market == "US":
                return self._fetch_us_stock(ak, code, start_date, end_date, period, adjust)
            elif market == "HK":
                return self._fetch_hk_stock(ak, code, start_date, end_date, period, adjust)
            else:
                return {"error": f"不支持的市场类型: {market}"}
        except Exception as exc:
            logger.warning("获取历史价格失败 [%s]: %s", stock_code, exc, exc_info=True)
            return {"error": f"获取历史价格失败: {exc}"}

    @staticmethod
    def _fetch_a_share(ak, code, start_date, end_date, period, adjust) -> dict:
        # 主数据源：东方财富
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            if df is not None and not df.empty:
                return _build_result(df, code, "A", period, adjust)
        except Exception as e:
            logger.info("东方财富历史数据不可用 [%s]，切换腾讯数据源: %s", code, e)

        # 备用数据源：腾讯（仅支持 A 股日线，不支持复权参数）
        try:
            tx_symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_symbol,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                return _build_result(df, code, "A", period, adjust)
        except Exception as e2:
            logger.warning("腾讯数据源也失败 [%s]: %s", code, e2)

        return _build_result(None, code, "A", period, adjust)

    def _fetch_us_stock(self, ak, code, start_date, end_date, period, adjust) -> dict:
        # 主数据源：东方财富
        try:
            us_symbol = self._resolve_us_symbol(code)
            if us_symbol:
                df = ak.stock_us_hist(
                    symbol=us_symbol,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
                if df is not None and not df.empty:
                    return _build_result(df, code, "US", period, adjust)
        except Exception as e:
            logger.info("东方财富美股数据不可用 [%s]，切换新浪数据源: %s", code, e)

        # 备用数据源：新浪（返回全量日线，需手动过滤日期）
        try:
            df = ak.stock_us_daily(symbol=code, adjust=adjust or "qfq")
            if df is not None and not df.empty:
                df = _filter_by_date(df, start_date, end_date)
                if not df.empty:
                    return _build_result(df, code, "US", period, adjust)
        except Exception as e2:
            logger.warning("新浪美股数据也失败 [%s]: %s", code, e2)

        return _build_result(None, code, "US", period, adjust)

    @staticmethod
    def _fetch_hk_stock(ak, code, start_date, end_date, period, adjust) -> dict:
        # 主数据源：东方财富
        try:
            df = ak.stock_hk_hist(
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
            if df is not None and not df.empty:
                return _build_result(df, code, "HK", period, adjust)
        except Exception as e:
            logger.info("东方财富港股数据不可用 [%s]，切换备用数据源: %s", code, e)

        # 备用数据源1：腾讯
        try:
            tx_symbol = f"hk{code}"
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_symbol,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                return _build_result(df, code, "HK", period, adjust)
        except Exception as e2:
            logger.info("腾讯港股数据不可用 [%s]: %s", code, e2)

        # 备用数据源2：新浪（返回全量日线）
        try:
            df = ak.stock_hk_daily(symbol=code, adjust=adjust or "qfq")
            if df is not None and not df.empty:
                df = _filter_by_date(df, start_date, end_date)
                if not df.empty:
                    return _build_result(df, code, "HK", period, adjust)
        except Exception as e3:
            logger.warning("新浪港股数据也失败 [%s]: %s", code, e3)

        return _build_result(None, code, "HK", period, adjust)

    @staticmethod
    def _resolve_us_symbol(code: str) -> str:
        """通过雪球接口获取美股交易所信息，构造东方财富格式的 symbol。

        例如 MSFT -> '105.MSFT'（NASDAQ），BABA -> '106.BABA'（NYSE）
        """
        if code in _us_prefix_cache:
            return _us_prefix_cache[code]

        try:
            from invest_research.services.xq_token_manager import call_xq_api

            df = call_xq_api(code)
            if df is None or df.empty:
                return ""

            exchange = ""
            for _, row in df.iterrows():
                item = str(row.get("item", ""))
                if item == "交易所":
                    exchange = str(row.get("value", "")).strip().upper()
                    break

            prefix = US_EXCHANGE_PREFIX.get(exchange, "")
            if not prefix:
                # 默认尝试 NASDAQ
                prefix = "105"

            symbol = f"{prefix}.{code}"
            _us_prefix_cache[code] = symbol
            return symbol
        except Exception:
            logger.warning("获取美股交易所前缀失败 [%s]", code, exc_info=True)
            return ""


def _filter_by_date(df, start_date: str, end_date: str):
    """按 YYYYMMDD 格式的日期范围过滤 DataFrame（新浪接口返回全量数据）。"""
    import pandas as pd

    if "date" not in df.columns:
        return df
    df["date"] = pd.to_datetime(df["date"])
    start = pd.to_datetime(start_date, format="%Y%m%d")
    end = pd.to_datetime(end_date, format="%Y%m%d")
    return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)


def _build_result(df, code: str, market: str, period: str, adjust: str) -> dict:
    """将 DataFrame 转为标准返回结构，含 stats 汇总。"""
    if df is None or df.empty:
        return {
            "market": market,
            "code": code,
            "period": period,
            "adjust": adjust,
            "data": [],
            "stats": {},
            "error": "未查询到历史数据",
        }

    # 统一列名映射（AKShare 中英文列名不一致）
    column_map = {
        "日期": "date", "date": "date", "Date": "date",
        "开盘": "open", "open": "open", "Open": "open",
        "收盘": "close", "close": "close", "Close": "close",
        "最高": "high", "high": "high", "High": "high",
        "最低": "low", "low": "low", "Low": "low",
        "成交量": "volume", "volume": "volume", "Volume": "volume",
        "成交额": "amount", "amount": "amount", "Amount": "amount",
        "涨跌幅": "change_pct", "振幅": "amplitude",
        "换手率": "turnover",
    }

    records = []
    for _, row in df.iterrows():
        record = {}
        for orig_col in df.columns:
            mapped = column_map.get(orig_col, orig_col)
            val = row[orig_col]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                val = None
            record[mapped] = val
        records.append(record)

    # 如果请求周线/月线但数据源返回的是日线，做服务端降采样
    if period in ("weekly", "monthly") and len(records) > 60:
        records = _resample(records, period)

    stats = _calc_stats(records, period)

    return {
        "market": market,
        "code": code,
        "period": period,
        "adjust": adjust,
        "data": records,
        "stats": stats,
        "error": "",
    }


def _calc_stats(records: list[dict], period: str = "daily") -> dict:
    """计算年化收益率、最大回撤、总收益率。"""
    if not records:
        return {}

    closes = []
    for r in records:
        c = r.get("close")
        if c is not None:
            try:
                closes.append(float(c))
            except (ValueError, TypeError):
                pass

    if len(closes) < 2:
        return {}

    start_price = closes[0]
    end_price = closes[-1]
    n_periods = len(closes)

    # 总收益率
    total_return_pct = (end_price / start_price - 1) * 100

    # 年化收益率：根据周期类型选择每年的期数
    periods_per_year = {"daily": 252, "weekly": 52, "monthly": 12}
    ppy = periods_per_year.get(period, 252)

    if n_periods > 1 and start_price > 0:
        annual_return_pct = ((end_price / start_price) ** (ppy / n_periods) - 1) * 100
    else:
        annual_return_pct = 0

    # 最大回撤
    max_drawdown_pct = 0.0
    peak = closes[0]
    for price in closes[1:]:
        if price > peak:
            peak = price
        drawdown = (price - peak) / peak * 100
        if drawdown < max_drawdown_pct:
            max_drawdown_pct = drawdown

    return {
        "total_return_pct": round(total_return_pct, 2),
        "annual_return_pct": round(annual_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "trading_days": n_periods,
        "start_price": round(start_price, 2),
        "end_price": round(end_price, 2),
    }


def _resample(records: list[dict], period: str) -> list[dict]:
    """将日线数据降采样为周线或月线。"""
    from datetime import datetime

    def get_group_key(date_str: str) -> str:
        try:
            dt = datetime.fromisoformat(str(date_str)[:10])
            if period == "weekly":
                # ISO 周：年-周号
                return f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
            else:
                return dt.strftime("%Y-%m")
        except Exception:
            return date_str[:7]

    groups: dict[str, list[dict]] = {}
    group_order: list[str] = []
    for r in records:
        key = get_group_key(str(r.get("date", "")))
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(r)

    result = []
    for key in group_order:
        bars = groups[key]
        opens = [b["open"] for b in bars if b.get("open") is not None]
        closes = [b["close"] for b in bars if b.get("close") is not None]
        highs = [b["high"] for b in bars if b.get("high") is not None]
        lows = [b["low"] for b in bars if b.get("low") is not None]
        volumes = [b.get("volume", 0) or 0 for b in bars]
        amounts = [b.get("amount", 0) or 0 for b in bars]

        if not closes:
            continue

        first_close = closes[0]
        last_close = closes[-1]
        change_pct = (last_close / first_close - 1) * 100 if first_close else 0

        result.append({
            "date": bars[0].get("date"),
            "open": opens[0] if opens else None,
            "close": last_close,
            "high": max(highs) if highs else None,
            "low": min(lows) if lows else None,
            "volume": sum(volumes),
            "amount": sum(amounts),
            "change_pct": round(change_pct, 2),
        })

    return result
