import hashlib
import logging
import random
import time
from datetime import datetime

from invest_research.config import get_settings
from invest_research.crawlers.base import BaseCrawler
from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]


class CLSCrawler(BaseCrawler):
    """财联社新闻爬虫，使用 crawl4ai 进行异步爬取。"""

    source_name = "cls"

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
            import asyncio
            return asyncio.run(self._async_crawl(keywords, framework_id, start_date, end_date))
        except Exception as e:
            logger.error(f"财联社爬取失败: {e}")
            return []

    async def _async_crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[NewsArticle]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        except ImportError:
            logger.error("crawl4ai 未安装，跳过财联社爬取")
            return []

        articles = []
        browser_config = BrowserConfig(
            headless=True,
            user_agent=random.choice(USER_AGENTS),
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            for keyword in keywords[:3]:
                try:
                    delay = random.uniform(
                        self.settings.crawl_random_delay_min,
                        self.settings.crawl_random_delay_max,
                    )
                    time.sleep(delay)

                    search_url = f"https://www.cls.cn/searchPage?keyword={keyword}&type=all"
                    run_config = CrawlerRunConfig(
                        wait_until="networkidle",
                    )
                    result = await crawler.arun(url=search_url, config=run_config)

                    if not result.success:
                        logger.warning(f"财联社页面加载失败: {keyword}")
                        continue

                    parsed = self._parse_results(
                        result.markdown, keyword, framework_id, start_date, end_date
                    )
                    articles.extend(parsed)
                except Exception as e:
                    logger.warning(f"财联社爬取关键词 '{keyword}' 失败: {e}")

        logger.info(f"财联社爬取完成，获取 {len(articles)} 条新闻")
        return articles

    def _parse_results(
        self,
        markdown_content: str,
        keyword: str,
        framework_id: int,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[NewsArticle]:
        articles = []
        lines = markdown_content.split("\n")

        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:
                continue

            # 从 markdown 中提取链接和标题
            if "[" in line and "](" in line:
                try:
                    title_start = line.index("[") + 1
                    title_end = line.index("]")
                    url_start = line.index("(", title_end) + 1
                    url_end = line.index(")", url_start)

                    title = line[title_start:title_end].strip()
                    url = line[url_start:url_end].strip()

                    if not title or not url or len(title) < 5:
                        continue
                    if keyword.lower() not in title.lower():
                        continue

                    url_hash = hashlib.sha256(url.encode()).hexdigest()
                    articles.append(NewsArticle(
                        framework_id=framework_id,
                        title=title,
                        source=self.source_name,
                        url=url,
                        url_hash=url_hash,
                        content_snippet="",
                        published_at=None,
                        crawled_at=datetime.now(),
                    ))
                except (ValueError, IndexError):
                    continue

        return articles
