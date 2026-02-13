from abc import ABC, abstractmethod
from datetime import datetime

from invest_research.models import NewsArticle


class BaseCrawler(ABC):
    source_name: str = "unknown"

    @abstractmethod
    def crawl(
        self,
        keywords: list[str],
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[NewsArticle]:
        ...
