import json
import logging
import sqlite3
from datetime import datetime

from invest_research.models import WeeklyAnalysis, NewsAnalysisItem

logger = logging.getLogger(__name__)


class AnalysisRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, analysis: WeeklyAnalysis) -> int:
        news_analyses_json = json.dumps(
            [item.model_dump() for item in analysis.news_analyses],
            ensure_ascii=False,
        )
        cursor = self.conn.execute(
            """
            INSERT INTO analyses (
                framework_id, week_start, week_end,
                news_analyses, weekly_summary
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                analysis.framework_id,
                analysis.week_start.isoformat(),
                analysis.week_end.isoformat(),
                news_analyses_json,
                analysis.weekly_summary,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recent(self, framework_id: int, weeks: int = 8) -> list[WeeklyAnalysis]:
        cursor = self.conn.execute(
            """
            SELECT * FROM analyses
            WHERE framework_id = ?
            ORDER BY week_end DESC
            LIMIT ?
            """,
            (framework_id, weeks),
        )
        return [self._row_to_model(row) for row in cursor.fetchall()]

    def get_latest(self, framework_id: int) -> WeeklyAnalysis | None:
        cursor = self.conn.execute(
            """
            SELECT * FROM analyses
            WHERE framework_id = ?
            ORDER BY week_end DESC
            LIMIT 1
            """,
            (framework_id,),
        )
        row = cursor.fetchone()
        return self._row_to_model(row) if row else None

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> WeeklyAnalysis:
        news_analyses_raw = json.loads(row["news_analyses"])
        news_analyses = [NewsAnalysisItem(**item) for item in news_analyses_raw]

        return WeeklyAnalysis(
            id=row["id"],
            framework_id=row["framework_id"],
            week_start=datetime.fromisoformat(row["week_start"]),
            week_end=datetime.fromisoformat(row["week_end"]),
            news_analyses=news_analyses,
            weekly_summary=row["weekly_summary"],
            created_at=row["created_at"],
        )
