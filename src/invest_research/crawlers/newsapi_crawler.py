import hashlib
import logging
from datetime import datetime

from invest_research.config import get_settings
from invest_research.crawlers.base import BaseCrawler
from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)


class NewsAPICrawler(BaseCrawler):
    source_name = "newsapi"

    def __init__(self):
        self.settings = get_settings()

    def crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[NewsArticle]:
        if not self.settings.newsapi_api_key:
            logger.warning("NewsAPI 密钥未配置，跳过国际新闻爬取")
            return []

        try:
            from newsapi import NewsApiClient
        except ImportError:
            logger.error("newsapi-python 未安装，跳过国际新闻爬取")
            return []

        api = NewsApiClient(api_key=self.settings.newsapi_api_key)
        query = " OR ".join(keywords[:5])

        kwargs = {"q": query, "sort_by": "publishedAt", "page_size": 50}
        if start_date:
            kwargs["from_param"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            kwargs["to"] = end_date.strftime("%Y-%m-%d")

        articles = []
        try:
            result = api.get_everything(**kwargs)
            for item in result.get("articles", []):
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue

                published_at = None
                if item.get("publishedAt"):
                    try:
                        published_at = datetime.fromisoformat(
                            item["publishedAt"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                url_hash = hashlib.sha256(url.encode()).hexdigest()
                content = item.get("description", "") or ""
                articles.append(NewsArticle(
                    framework_id=framework_id,
                    title=title,
                    source=f"newsapi:{item.get('source', {}).get('name', '')}",
                    url=url,
                    url_hash=url_hash,
                    content_snippet=content[:500],
                    published_at=published_at,
                    crawled_at=datetime.now(),
                ))
        except Exception as e:
            logger.warning(f"NewsAPI 爬取失败: {e}")

        logger.info(f"NewsAPI 爬取完成，获取 {len(articles)} 条新闻")
        return articles
