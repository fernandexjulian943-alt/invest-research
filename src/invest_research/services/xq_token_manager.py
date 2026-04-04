"""雪球 token 管理器，自动检测过期并通过 Playwright 刷新。

特性:
- token 持久化到文件，服务重启不丢失
- 刷新失败后冷却 10 分钟，避免频繁启动浏览器
- 刷新成功的 token 缓存 2 小时，期间不再刷新
"""

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_cached_token: str | None = None
_token_lock = threading.Lock()
_last_refresh_time: float = 0  # 上次成功刷新的时间戳
_last_fail_time: float = 0  # 上次失败的时间戳

_TOKEN_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "xq_token.json"
_TOKEN_VALID_SECONDS = 2 * 3600  # token 有效期 2 小时
_FAIL_COOLDOWN_SECONDS = 600  # 刷新失败后冷却 10 分钟


def _load_token_from_file() -> str | None:
    """从文件加载持久化的 token。"""
    global _cached_token, _last_refresh_time
    try:
        if _TOKEN_FILE.exists():
            data = json.loads(_TOKEN_FILE.read_text())
            saved_time = data.get("time", 0)
            # 文件中的 token 未超过有效期才使用
            if time.time() - saved_time < _TOKEN_VALID_SECONDS:
                _cached_token = data["token"]
                _last_refresh_time = saved_time
                logger.info("从文件恢复雪球 token（%.0f 分钟前保存）", (time.time() - saved_time) / 60)
                return _cached_token
    except Exception as exc:
        logger.debug("加载 token 文件失败: %s", exc)
    return None


def _save_token_to_file(token: str) -> None:
    """将 token 持久化到文件。"""
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(json.dumps({"token": token, "time": time.time()}))
    except Exception as exc:
        logger.debug("保存 token 文件失败: %s", exc)


def get_token() -> str | None:
    """返回当前缓存的 token，无缓存则尝试从文件加载。"""
    if _cached_token:
        return _cached_token
    return _load_token_from_file()


def _should_refresh() -> bool:
    """判断是否应该刷新 token。"""
    now = time.time()
    # 上次成功刷新还在有效期内，不刷新
    if _last_refresh_time and now - _last_refresh_time < _TOKEN_VALID_SECONDS:
        return False
    # 上次失败还在冷却期内，不刷新
    if _last_fail_time and now - _last_fail_time < _FAIL_COOLDOWN_SECONDS:
        logger.debug("token 刷新冷却中，跳过（%.0f 秒后可重试）",
                      _FAIL_COOLDOWN_SECONDS - (now - _last_fail_time))
        return False
    return True


def refresh_token() -> str | None:
    """通过 Playwright 无头浏览器访问雪球首页，提取 xq_a_token cookie。

    返回新 token 字符串；若刷新失败返回 None。
    内置冷却机制：失败后 10 分钟内不重试，成功后 2 小时内不重复刷新。
    """
    global _cached_token, _last_refresh_time, _last_fail_time

    if not _should_refresh():
        return _cached_token

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright 未安装，无法自动刷新雪球 token")
        _last_fail_time = time.time()
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto("https://xueqiu.com/", timeout=30000)
            # 等待 JS 设置 cookie（雪球的 xq_a_token 由前端 JS 写入）
            time.sleep(3)

            cookies = context.cookies("https://xueqiu.com")
            token = ""
            for cookie in cookies:
                if cookie["name"] == "xq_a_token":
                    token = cookie["value"]
                    break

            browser.close()

        if token:
            _cached_token = token
            _last_refresh_time = time.time()
            _save_token_to_file(token)
            logger.info("雪球 token 刷新成功")
            return token

        logger.warning("未在 cookie 中找到 xq_a_token")
        _last_fail_time = time.time()
        return None
    except Exception as exc:
        logger.warning("Playwright 刷新雪球 token 失败: %s", exc)
        _last_fail_time = time.time()
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
        # 双重检查：可能其他线程已经刷新了
        current = get_token()
        if current and current != token:
            new_token = current
        else:
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
