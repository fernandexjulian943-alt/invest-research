"""xq_token_manager 单元测试。"""

import sys
import pytest
from unittest.mock import patch, MagicMock

import invest_research.services.xq_token_manager as token_mgr


@pytest.fixture(autouse=True)
def _reset_cached_token():
    """每个测试前重置缓存 token。"""
    token_mgr._cached_token = None
    yield
    token_mgr._cached_token = None


def _create_mock_akshare():
    mock_ak = MagicMock()
    return mock_ak


class TestCallXqApiNormalPath:
    """正常调用路径：AKShare 直接成功。"""

    def test_should_return_dataframe_when_no_cached_token(self):
        mock_ak = _create_mock_akshare()
        expected_df = MagicMock()
        mock_ak.stock_individual_spot_xq.return_value = expected_df

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            result = token_mgr.call_xq_api("SH600519")

        assert result is expected_df
        mock_ak.stock_individual_spot_xq.assert_called_once_with(symbol="SH600519")

    def test_should_pass_cached_token_when_available(self):
        token_mgr._cached_token = "test_token_123"
        mock_ak = _create_mock_akshare()
        expected_df = MagicMock()
        mock_ak.stock_individual_spot_xq.return_value = expected_df

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            result = token_mgr.call_xq_api("SH600519")

        assert result is expected_df
        mock_ak.stock_individual_spot_xq.assert_called_once_with(
            symbol="SH600519", token="test_token_123"
        )


class TestCallXqApiTokenExpiredRefresh:
    """token 过期自动刷新路径：第一次 KeyError → 刷新 → 第二次成功。"""

    def test_should_refresh_and_retry_when_key_error(self):
        mock_ak = _create_mock_akshare()
        expected_df = MagicMock()
        # 第一次 KeyError，第二次成功
        mock_ak.stock_individual_spot_xq.side_effect = [
            KeyError("data"),
            expected_df,
        ]

        with (
            patch.dict(sys.modules, {"akshare": mock_ak}),
            patch.object(token_mgr, "refresh_token", return_value="new_token_456") as mock_refresh,
        ):
            result = token_mgr.call_xq_api("SH600519")

        assert result is expected_df
        mock_refresh.assert_called_once()
        # 第二次调用应该带新 token
        assert mock_ak.stock_individual_spot_xq.call_count == 2
        second_call = mock_ak.stock_individual_spot_xq.call_args_list[1]
        assert second_call.kwargs.get("token") == "new_token_456"


class TestCallXqApiFallback:
    """Playwright 刷新失败的回退路径。"""

    def test_should_fallback_to_default_when_refresh_fails(self):
        mock_ak = _create_mock_akshare()
        expected_df = MagicMock()
        # 第一次 KeyError，刷新失败，回退调用成功
        mock_ak.stock_individual_spot_xq.side_effect = [
            KeyError("data"),
            expected_df,
        ]

        with (
            patch.dict(sys.modules, {"akshare": mock_ak}),
            patch.object(token_mgr, "refresh_token", return_value=None) as mock_refresh,
        ):
            result = token_mgr.call_xq_api("SH600519")

        assert result is expected_df
        mock_refresh.assert_called_once()
        # 回退调用不带 token
        assert mock_ak.stock_individual_spot_xq.call_count == 2
        fallback_call = mock_ak.stock_individual_spot_xq.call_args_list[1]
        assert "token" not in fallback_call.kwargs

    def test_should_propagate_error_when_all_attempts_fail(self):
        mock_ak = _create_mock_akshare()
        mock_ak.stock_individual_spot_xq.side_effect = KeyError("data")

        with (
            patch.dict(sys.modules, {"akshare": mock_ak}),
            patch.object(token_mgr, "refresh_token", return_value=None),
        ):
            with pytest.raises(KeyError):
                token_mgr.call_xq_api("SH600519")


class TestRefreshToken:
    """refresh_token 的边界测试。"""

    def test_should_return_none_when_playwright_not_installed(self):
        with patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            # 强制 import 失败
            original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

            def mock_import(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    raise ImportError("No module named 'playwright'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = token_mgr.refresh_token()

        assert result is None
