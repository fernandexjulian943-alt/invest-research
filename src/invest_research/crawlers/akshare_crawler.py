import hashlib
import logging
import time
from datetime import datetime

from invest_research.config import get_settings
from invest_research.crawlers.base import BaseCrawler
from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)


class AKShareCrawler(BaseCrawler):
    source_name = "akshare"

    def __init__(self):
        self.settings = get_settings()

    def crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[NewsArticle]:
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare 未安装，跳过 A 股新闻爬取")
            return []

        articles = []
        for keyword in keywords:
            try:
                time.sleep(self.settings.crawl_polite_delay)
                df = ak.stock_news_em(symbol=keyword)
                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    title = str(row.get("新闻标题", ""))
                    url = str(row.get("新闻链接", ""))
                    content = str(row.get("新闻内容", ""))[:500]
                    pub_date = row.get("发布时间", "")

                    if not title or not url:
                        continue

                    published_at = None
                    if pub_date:
                        try:
                            published_at = datetime.strptime(str(pub_date), "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass

                    if start_date and published_at and published_at < start_date:
                        continue
                    if end_date and published_at and published_at > end_date:
                        continue

                    url_hash = hashlib.sha256(url.encode()).hexdigest()
                    articles.append(NewsArticle(
                        framework_id=framework_id,
                        title=title,
                        source=self.source_name,
                        url=url,
                        url_hash=url_hash,
                        content_snippet=content,
                        published_at=published_at,
                        crawled_at=datetime.now(),
                    ))
            except Exception as e:
                logger.warning(f"AKShare 爬取关键词 '{keyword}' 失败: {e}")

        logger.info(f"AKShare 爬取完成，获取 {len(articles)} 条新闻")
        return articles
