"""雪球 token 管理器，自动检测过期并通过 Playwright 刷新。"""

import logging
import threading

logger = logging.getLogger(__name__)

_cached_token: str | None = None
_token_lock = threading.Lock()


def get_token() -> str | None:
    """返回当前缓存的 token，无缓存则返回 None（使用 AKShare 默认值）。"""
    return _cached_token


def refresh_token() -> str | None:
    """通过 Playwright 无头浏览器访问雪球页面，提取 xq_a_token cookie。

    返回新 token 字符串；若刷新失败返回 None。
    """
    global _cached_token

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright 未安装，无法自动刷新雪球 token")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://xueqiu.com/S/SH600519", wait_until="networkidle", timeout=30000)

            cookies = context.cookies("https://xueqiu.com")
            token = ""
            for cookie in cookies:
                if cookie["name"] == "xq_a_token":
                    token = cookie["value"]
                    break

            browser.close()

        if token:
            _cached_token = token
            logger.info("雪球 token 刷新成功")
            return token

        logger.warning("未在 cookie 中找到 xq_a_token")
        return None
    except Exception as exc:
        logger.warning("Playwright 刷新雪球 token 失败: %s", exc, exc_info=True)
        return None


def call_xq_api(symbol: str):
    """封装 ak.stock_individual_spot_xq 调用，自动处理 token 过期重试。

    流程:
    1. 使用当前 token 调用
    2. 若捕获 KeyError（token 过期），刷新 token 并重试
    3. 若 Playwright 刷新失败，回退到不传 token

    返回: DataFrame（与 ak.stock_individual_spot_xq 返回格式一致）
    """
    import akshare as ak

    token = get_token()

    # 第一次尝试
    try:
        if token:
            return ak.stock_individual_spot_xq(symbol=symbol, token=token)
        return ak.stock_individual_spot_xq(symbol=symbol)
    except KeyError:
        logger.info("雪球 token 疑似过期，尝试刷新 [symbol=%s]", symbol)

    # token 过期，加锁刷新
    with _token_lock:
        new_token = refresh_token()

    # 第二次尝试：使用刷新后的 token
    if new_token:
        try:
            return ak.stock_individual_spot_xq(symbol=symbol, token=new_token)
        except KeyError:
            logger.warning("刷新 token 后仍然失败 [symbol=%s]", symbol)

    # 回退：不传 token，使用 AKShare 内置默认值
    logger.info("回退到 AKShare 默认 token [symbol=%s]", symbol)
    return ak.stock_individual_spot_xq(symbol=symbol)
