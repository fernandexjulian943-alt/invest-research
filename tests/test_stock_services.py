"""股票数据查询服务的单元测试。"""

import sys
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from invest_research.services.market_utils import (
    detect_market,
    normalize_stock_code,
    build_xq_symbol,
)
from invest_research.services.stock_quote_service import StockQuoteService
from invest_research.services.stock_history_service import StockHistoryService, _us_prefix_cache


# ============================================================
# market_utils 测试
# ============================================================

class TestDetectMarket:
    def test_should_return_a_when_6_digit_code(self):
        assert detect_market("600519") == "A"
        assert detect_market("000001") == "A"
        assert detect_market("300750") == "A"

    def test_should_return_hk_when_5_digit_code(self):
        assert detect_market("00700") == "HK"
        assert detect_market("09988") == "HK"

    def test_should_return_us_when_alpha_code(self):
        assert detect_market("MSFT") == "US"
        assert detect_market("AAPL") == "US"
        assert detect_market("PDD") == "US"

    def test_should_return_empty_when_unknown_format(self):
        assert detect_market("1234") == ""
        assert detect_market("1234567") == ""
        assert detect_market("123ABC") == ""

    def test_should_strip_dot_suffix(self):
        assert detect_market("000001.SZ") == "A"
        assert detect_market("600519.SH") == "A"


class TestNormalizeStockCode:
    def test_should_take_first_of_slash_separated(self):
        assert normalize_stock_code("GOOGL/GOOG") == "GOOGL"

    def test_should_strip_dot_suffix(self):
        assert normalize_stock_code("000001.SZ") == "000001"

    def test_should_strip_whitespace(self):
        assert normalize_stock_code("  MSFT  ") == "MSFT"

    def test_should_handle_plain_code(self):
        assert normalize_stock_code("600519") == "600519"

    def test_should_pad_short_hk_codes_to_5_digits(self):
        assert normalize_stock_code("700") == "00700"
        assert normalize_stock_code("0700") == "00700"
        assert normalize_stock_code("9988") == "09988"
        assert normalize_stock_code("1") == "00001"


class TestBuildXqSymbol:
    def test_should_prefix_sh_for_6xx(self):
        assert build_xq_symbol("600519", "A") == "SH600519"

    def test_should_prefix_sz_for_0xx(self):
        assert build_xq_symbol("000001", "A") == "SZ000001"

    def test_should_prefix_sz_for_3xx(self):
        assert build_xq_symbol("300750", "A") == "SZ300750"

    def test_should_return_as_is_for_us(self):
        assert build_xq_symbol("MSFT", "US") == "MSFT"

    def test_should_return_as_is_for_hk(self):
        assert build_xq_symbol("00700", "HK") == "00700"


# ============================================================
# Mock helpers
# ============================================================

def _make_xq_df(data_dict: dict) -> pd.DataFrame:
    """构造 stock_individual_spot_xq 返回的 DataFrame 结构。"""
    rows = [{"item": k, "value": v} for k, v in data_dict.items()]
    return pd.DataFrame(rows)


def _make_hist_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"日期": "2026-01-02", "开盘": 100.0, "收盘": 105.0, "最高": 106.0, "最低": 99.0, "成交量": 1000000, "成交额": 100000000, "涨跌幅": 2.5, "换手率": 1.2},
        {"日期": "2026-01-03", "开盘": 105.0, "收盘": 103.0, "最高": 107.0, "最低": 102.0, "成交量": 800000, "成交额": 80000000, "涨跌幅": -1.9, "换手率": 0.9},
    ])


def _create_mock_akshare():
    """创建一个 mock akshare 模块。"""
    mock_ak = MagicMock()
    return mock_ak


# ============================================================
# StockQuoteService 测试
# ============================================================

class TestStockQuoteService:
    def test_should_return_error_when_empty_code(self):
        service = StockQuoteService()
        result = service.fetch_quote("")
        assert result["error"]

    def test_should_return_error_when_unrecognized_code(self):
        service = StockQuoteService()
        result = service.fetch_quote("???")
        assert result["error"]

    def test_should_return_structured_quote_for_a_share(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_individual_spot_xq.return_value = _make_xq_df({
            "名称": "贵州茅台",
            "现价": "1800.00",
            "涨跌": "15.50",
            "涨幅": "0.87",
            "今开": "1790.00",
            "最高": "1810.00",
            "最低": "1785.00",
            "昨收": "1784.50",
            "成交量": "12345678",
            "成交额": "22000000000",
            "市盈率(TTM)": "30.5",
            "市净率": "10.2",
            "资产净值/总市值": "2260000000000",
            "股息率(TTM)": "1.5",
            "52周最高": "2000.00",
            "52周最低": "1500.00",
            "货币": "CNY",
            "时间": "2026-02-19 15:00:00",
        })

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockQuoteService()
            result = service.fetch_quote("600519")

        assert result["error"] == ""
        assert result["market"] == "A"
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"
        assert result["price"] == 1800.0
        assert result["change"] == 15.5
        assert result["change_pct"] == 0.87
        assert result["currency"] == "CNY"
        mock_ak.stock_individual_spot_xq.assert_called_once_with(symbol="SH600519")

    def test_should_return_error_when_api_fails(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_individual_spot_xq.side_effect = Exception("网络超时")

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockQuoteService()
            result = service.fetch_quote("MSFT")

        assert "网络超时" in result["error"]


# ============================================================
# StockHistoryService 测试
# ============================================================

class TestStockHistoryService:
    def test_should_return_error_when_empty_code(self):
        service = StockHistoryService()
        result = service.fetch_history("", "20260101", "20260219")
        assert result["error"]

    def test_should_return_error_when_unrecognized_code(self):
        service = StockHistoryService()
        result = service.fetch_history("???", "20260101", "20260219")
        assert result["error"]

    def test_should_return_a_share_history(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_zh_a_hist.return_value = _make_hist_df()

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockHistoryService()
            result = service.fetch_history("600519", "20260101", "20260219")

        assert result["error"] == ""
        assert result["market"] == "A"
        assert result["code"] == "600519"
        assert len(result["data"]) == 2
        assert result["data"][0]["close"] == 105.0
        mock_ak.stock_zh_a_hist.assert_called_once_with(
            symbol="600519", period="daily",
            start_date="20260101", end_date="20260219", adjust="qfq",
        )

    def test_should_return_hk_history(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_hk_hist.return_value = _make_hist_df()

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockHistoryService()
            result = service.fetch_history("00700", "20260101", "20260219")

        assert result["error"] == ""
        assert result["market"] == "HK"
        mock_ak.stock_hk_hist.assert_called_once()

    def test_should_resolve_us_prefix_and_fetch(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_individual_spot_xq.return_value = _make_xq_df({
            "交易所": "NASDAQ",
        })
        mock_ak.stock_us_hist.return_value = _make_hist_df()

        # 清除缓存以确保测试隔离
        _us_prefix_cache.pop("MSFT", None)

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockHistoryService()
            result = service.fetch_history("MSFT", "20260101", "20260219")

        assert result["error"] == ""
        assert result["market"] == "US"
        mock_ak.stock_us_hist.assert_called_once_with(
            symbol="105.MSFT", period="daily",
            start_date="20260101", end_date="20260219", adjust="qfq",
        )

    def test_should_return_error_when_empty_dataframe(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockHistoryService()
            result = service.fetch_history("600519", "20260101", "20260219")

        assert result["error"]
        assert result["data"] == []

    def test_should_return_error_when_api_exception(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_zh_a_hist.side_effect = Exception("接口限流")

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            service = StockHistoryService()
            result = service.fetch_history("600519", "20260101", "20260219")

        assert "接口限流" in result["error"]
