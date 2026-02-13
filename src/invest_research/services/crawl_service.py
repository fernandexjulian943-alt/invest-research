import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher

from invest_research.config import get_settings
from invest_research.crawlers.akshare_crawler import AKShareCrawler
from invest_research.crawlers.cls_crawler import CLSCrawler
from invest_research.crawlers.newsapi_crawler import NewsAPICrawler
from invest_research.crawlers.rss_crawler import RSSCrawler
from invest_research.crawlers.base import BaseCrawler
from invest_research.data.news_repo import NewsRepo
from invest_research.models import AnalysisFramework, NewsArticle

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3


class CrawlService:
    def __init__(self, news_repo: NewsRepo):
        self.news_repo = news_repo
        self.settings = get_settings()
        self._failure_counts: dict[str, int] = {}

    def crawl_all(
        self,
        framework: AnalysisFramework,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        crawlers: list[BaseCrawler] = [
            AKShareCrawler(),
            NewsAPICrawler(),
            RSSCrawler(),
            CLSCrawler(),
        ]

        all_articles: list[NewsArticle] = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for crawler in crawlers:
                if self._is_circuit_broken(crawler.source_name):
                    logger.warning(f"熔断器已触发，跳过 {crawler.source_name}")
                    continue
                future = executor.submit(
                    crawler.crawl,
                    framework.keywords,
                    framework.id,
                    start_date,
                    end_date,
                )
                futures[future] = crawler.source_name

            for future in as_completed(futures):
                source = futures[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                    self._reset_failure(source)
                    logger.info(f"{source} 返回 {len(articles)} 条新闻")
                except Exception as e:
                    self._record_failure(source)
                    logger.error(f"{source} 爬取失败: {e}")

        # 去重
        deduplicated = self._deduplicate(all_articles)

        # 存储
        inserted_count = 0
        for article in deduplicated:
            if self.news_repo.insert_if_not_exists(article):
                inserted_count += 1

        logger.info(f"爬取完成: 总计 {len(all_articles)} 条，去重后 {len(deduplicated)} 条，新增 {inserted_count} 条")
        return inserted_count

    def _deduplicate(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        seen_hashes: set[str] = set()
        seen_titles: list[str] = []
        result: list[NewsArticle] = []

        for article in articles:
            if article.url_hash in seen_hashes:
                continue

            is_duplicate_title = False
            for existing_title in seen_titles:
                similarity = SequenceMatcher(None, article.title, existing_title).ratio()
                if similarity >= self.settings.dedup_title_similarity_threshold:
                    is_duplicate_title = True
                    break

            if is_duplicate_title:
                continue

            seen_hashes.add(article.url_hash)
            seen_titles.append(article.title)
            result.append(article)

        return result

    def _is_circuit_broken(self, source: str) -> bool:
        return self._failure_counts.get(source, 0) >= MAX_CONSECUTIVE_FAILURES

    def _record_failure(self, source: str) -> None:
        self._failure_counts[source] = self._failure_counts.get(source, 0) + 1

    def _reset_failure(self, source: str) -> None:
        self._failure_counts[source] = 0
