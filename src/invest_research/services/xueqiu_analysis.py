"""雪球股票讨论页抓取服务。

通过 Playwright 模拟浏览器访问雪球，在页面上下文内调用帖子 API，
绕过阿里云 WAF 拦截。

策略：先访问股票详情页通过 WAF 挑战，再用页面内 fetch 调用帖子 JSON API。
"""

import logging
import re
import threading
import time

from invest_research.services.market_utils import build_xq_symbol, detect_market

logger = logging.getLogger(__name__)

_XQ_POST_URL = "https://xueqiu.com"

# 并发控制：同一时刻只允许一个 Playwright 实例运行，防止多个 Chromium 爆内存
_browser_lock = threading.Lock()

# 反检测：Playwright 启动参数和初始化脚本
_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]
_ANTI_DETECT_SCRIPT = """
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
    window.chrome = { runtime: {} };
"""
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def fetch_xueqiu_posts(stock_code: str, limit: int = 15) -> dict:
    """抓取雪球股票讨论页的帖子列表。

    Args:
        stock_code: 标准化股票代码（如 600519、MSFT、00700）
        limit: 返回帖子数量上限

    Returns:
        {
            "stock_code": str,
            "symbol": str,
            "posts": [{user, followers, title, url, time, likes, comments}],
            "error": str,
        }
    """
    market = detect_market(stock_code)
    if not market:
        return {"stock_code": stock_code, "symbol": "", "posts": [], "error": "无法识别的股票代码"}

    symbol = build_xq_symbol(stock_code, market)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"stock_code": stock_code, "symbol": symbol, "posts": [], "error": "playwright 未安装"}

    # 非阻塞获取锁：如果已有请求在跑，直接返回提示
    if not _browser_lock.acquire(blocking=False):
        return {"stock_code": stock_code, "symbol": symbol, "posts": [], "error": "另一个雪球查询正在进行中，请稍后重试"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_BROWSER_ARGS)
            context = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            context.add_init_script(_ANTI_DETECT_SCRIPT)
            page = context.new_page()

            # 第1步：访问股票详情页，通过 WAF 挑战
            page_url = f"https://xueqiu.com/S/{symbol}"
            logger.info("访问雪球股票页: %s", page_url)
            page.goto(page_url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(8)

            title = page.title()
            if "Verification" in title:
                logger.warning("雪球 WAF 验证未通过，页面标题: %s", title)
                browser.close()
                return {"stock_code": stock_code, "symbol": symbol, "posts": [], "error": "雪球 WAF 验证未通过，请稍后重试"}

            # 第2步：在页面上下文内用 fetch 调用帖子 API
            api_url = f"/query/v1/symbol/search/status.json?symbol={symbol}&count={limit}&comment=0&source=all"
            raw_data = page.evaluate(
                """async (url) => {
                    try {
                        const r = await fetch(url);
                        return await r.json();
                    } catch(e) { return { error: e.message }; }
                }""",
                api_url,
            )

            browser.close()

        if not raw_data or "error" in raw_data:
            err = raw_data.get("error", "未知错误") if raw_data else "空响应"
            return {"stock_code": stock_code, "symbol": symbol, "posts": [], "error": f"API 调用失败: {err}"}

        posts = _parse_api_response(raw_data)

        # 按粉丝数 + 互动量排序
        posts.sort(key=lambda x: (x["followers"], x["likes"] + x["comments"]), reverse=True)
        posts = posts[:limit]

        if not posts:
            return {"stock_code": stock_code, "symbol": symbol, "posts": [], "error": "未获取到讨论帖子"}

        return {"stock_code": stock_code, "symbol": symbol, "posts": posts, "error": ""}

    except Exception as exc:
        logger.warning("抓取雪球讨论页失败 [%s]: %s", symbol, exc)
        return {"stock_code": stock_code, "symbol": symbol, "posts": [], "error": f"抓取失败: {exc}"}
    finally:
        _browser_lock.release()


def _parse_api_response(data: dict) -> list[dict]:
    """解析雪球帖子 API 响应。"""
    posts = []
    for item in data.get("list") or []:
        user_info = item.get("user") or {}
        user_name = user_info.get("screen_name", "")
        if not user_name:
            continue

        followers = user_info.get("followers_count", 0) or 0
        user_id = user_info.get("id", "")

        title = item.get("title") or item.get("description") or item.get("text", "")
        title = _strip_html(title)
        if not title:
            continue
        if len(title) > 120:
            title = title[:120] + "..."

        post_id = item.get("id", "")
        url = f"{_XQ_POST_URL}/{user_id}/{post_id}" if user_id and post_id else ""

        posts.append({
            "user": user_name,
            "followers": followers,
            "title": title,
            "url": url,
            "time": _format_timestamp(item.get("created_at", 0)),
            "likes": item.get("like_count", 0) or 0,
            "comments": item.get("reply_count", 0) or 0,
        })

    return posts


def _strip_html(text: str) -> str:
    """简单去除 HTML 标签。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_timestamp(ts) -> str:
    """将毫秒时间戳转为可读日期。"""
    if not ts:
        return ""
    try:
        if isinstance(ts, (int, float)) and ts > 1e12:
            ts = ts / 1000
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except Exception:
        return str(ts)
