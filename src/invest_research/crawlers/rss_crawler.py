import hashlib
import logging
from datetime import datetime

import feedparser

from invest_research.crawlers.base import BaseCrawler
from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)


class RSSCrawler(BaseCrawler):
    source_name = "rss"

    def crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[NewsArticle]:
        from invest_research.data.framework_repo import FrameworkRepo
        from invest_research.data.database import get_connection

        conn = get_connection()
        repo = FrameworkRepo(conn)
        framework = repo.get_by_id(framework_id)
        conn.close()

        if not framework or not framework.rss_feeds:
            logger.info("无 RSS 源配置，跳过 RSS 爬取")
            return []

        articles = []
        keyword_set = {kw.lower() for kw in keywords}

        for feed_url in framework.rss_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    if not title or not link:
                        continue

                    # 关键词过滤
                    text_lower = (title + " " + entry.get("summary", "")).lower()
                    is_relevant = any(kw in text_lower for kw in keyword_set)
                    if not is_relevant:
                        continue

                    published_at = None
                    if entry.get("published_parsed"):
                        try:
                            published_at = datetime(*entry.published_parsed[:6])
                        except (TypeError, ValueError):
                            pass

                    if start_date and published_at and published_at < start_date:
                        continue
                    if end_date and published_at and published_at > end_date:
                        continue

                    url_hash = hashlib.sha256(link.encode()).hexdigest()
                    summary = entry.get("summary", "")[:500]
                    articles.append(NewsArticle(
                        framework_id=framework_id,
                        title=title,
                        source=f"rss:{feed_url[:50]}",
                        url=link,
                        url_hash=url_hash,
                        content_snippet=summary,
                        published_at=published_at,
                        crawled_at=datetime.now(),
                    ))
            except Exception as e:
                logger.warning(f"RSS 源 '{feed_url}' 爬取失败: {e}")

        logger.info(f"RSS 爬取完成，获取 {len(articles)} 条新闻")
        return articles
