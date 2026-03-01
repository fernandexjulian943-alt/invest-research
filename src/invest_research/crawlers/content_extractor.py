import logging

logger = logging.getLogger(__name__)

SNIPPET_MAX_CHARS = 500


def extract_content(url: str) -> str:
    """使用 trafilatura 提取 URL 对应的正文内容，返回前 500 字符。"""
    try:
        import trafilatura
    except ImportError:
        logger.error("trafilatura 未安装，无法提取正文")
        return ""

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded) or ""
        return text[:SNIPPET_MAX_CHARS]
    except Exception as e:
        logger.debug(f"提取正文失败 {url}: {e}")
        return ""
