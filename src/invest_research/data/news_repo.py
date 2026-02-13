import hashlib
import json
import logging
import sqlite3
from datetime import datetime

from invest_research.models import NewsArticle

logger = logging.getLogger(__name__)


class NewsRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_if_not_exists(self, article: NewsArticle) -> bool:
        if not article.url_hash:
            article.url_hash = hashlib.sha256(article.url.encode()).hexdigest()

        try:
            self.conn.execute(
                """
                INSERT INTO news_articles (
                    framework_id, title, source, url, url_hash,
                    content_snippet, published_at, crawled_at, relevance_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.framework_id,
                    article.title,
                    article.source,
                    article.url,
                    article.url_hash,
                    article.content_snippet,
                    article.published_at.isoformat() if article.published_at else None,
                    article.crawled_at.isoformat() if article.crawled_at else datetime.now().isoformat(),
                    article.relevance_score,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_by_framework(
        self,
        framework_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 200,
    ) -> list[NewsArticle]:
        query = "SELECT * FROM news_articles WHERE framework_id = ?"
        params: list = [framework_id]

        if start_date:
            query += " AND crawled_at >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND crawled_at <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY crawled_at DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [self._row_to_model(row) for row in cursor.fetchall()]

    def count_by_framework(self, framework_id: int) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM news_articles WHERE framework_id = ?", (framework_id,)
        )
        return cursor.fetchone()[0]

    def exists_by_url_hash(self, url_hash: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM news_articles WHERE url_hash = ?", (url_hash,)
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> NewsArticle:
        published_at = None
        if row["published_at"]:
            try:
                published_at = datetime.fromisoformat(row["published_at"])
            except ValueError:
                pass

        crawled_at = None
        if row["crawled_at"]:
            try:
                crawled_at = datetime.fromisoformat(row["crawled_at"])
            except ValueError:
                pass

        return NewsArticle(
            id=row["id"],
            framework_id=row["framework_id"],
            title=row["title"],
            source=row["source"],
            url=row["url"],
            url_hash=row["url_hash"],
            content_snippet=row["content_snippet"],
            published_at=published_at,
            crawled_at=crawled_at,
            relevance_score=row["relevance_score"],
        )
