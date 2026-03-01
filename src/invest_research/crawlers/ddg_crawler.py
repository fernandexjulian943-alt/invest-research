import hashlib
import logging
from datetime import datetime

from invest_research.crawlers.base import BaseCrawler
from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)


class DdgCrawler(BaseCrawler):
    source_name = "duckduckgo"

    def crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[NewsArticle]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.error("duckduckgo-search 未安装，跳过 DuckDuckGo 新闻爬取")
            return []

        articles: list[NewsArticle] = []
        for keyword in keywords:
            try:
                results = DDGS().news(
                    keywords=keyword,
                    region="wt-wt",
                    timelimit="w",
                    max_results=20,
                )
                for item in results:
                    title = item.get("title", "")
                    url = item.get("url", "")
                    if not title or not url:
                        continue

                    published_at = self._parse_date(item.get("date", ""))
                    if start_date and published_at and published_at < start_date:
                        continue
                    if end_date and published_at and published_at > end_date:
                        continue

                    url_hash = hashlib.sha256(url.encode()).hexdigest()
                    body = item.get("body", "") or ""
                    source = item.get("source", "") or ""

                    articles.append(NewsArticle(
                        framework_id=framework_id,
                        title=title,
                        source=f"duckduckgo:{source}",
                        url=url,
                        url_hash=url_hash,
                        content_snippet=body[:500],
                        published_at=published_at,
                        crawled_at=datetime.now(),
                    ))
            except Exception as e:
                logger.warning(f"DuckDuckGo 搜索关键词 '{keyword}' 失败: {e}")

        logger.info(f"DuckDuckGo 爬取完成，获取 {len(articles)} 条新闻")
        return articles

    def _parse_date(self, date_str: str) -> datetime | None:
        if not date_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None
