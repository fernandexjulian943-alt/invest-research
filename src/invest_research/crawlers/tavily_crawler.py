import hashlib
import logging
from datetime import datetime

from invest_research.config import get_settings
from invest_research.crawlers.base import BaseCrawler
from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)


class TavilyCrawler(BaseCrawler):
    source_name = "tavily"

    def __init__(self):
        self.settings = get_settings()

    def crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[NewsArticle]:
        if not self.settings.tavily_api_key:
            logger.warning("Tavily API 密钥未配置，跳过 Tavily 新闻搜索")
            return []

        try:
            from tavily import TavilyClient
        except ImportError:
            logger.error("tavily-python 未安装，跳过 Tavily 新闻搜索")
            return []

        client = TavilyClient(api_key=self.settings.tavily_api_key)
        query = " ".join(keywords)

        articles: list[NewsArticle] = []
        try:
            result = client.search(
                query=query,
                topic="news",
                max_results=10,
                include_raw_content=False,
            )
            for item in result.get("results", []):
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue

                url_hash = hashlib.sha256(url.encode()).hexdigest()
                content = item.get("content", "") or ""

                articles.append(NewsArticle(
                    framework_id=framework_id,
                    title=title,
                    source="tavily",
                    url=url,
                    url_hash=url_hash,
                    content_snippet=content[:500],
                    published_at=None,
                    crawled_at=datetime.now(),
                ))
        except Exception as e:
            logger.warning(f"Tavily 搜索失败: {e}")

        logger.info(f"Tavily 爬取完成，获取 {len(articles)} 条新闻")
        return articles
