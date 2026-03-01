import json
import sqlite3
from datetime import datetime

from invest_research.models import AnalysisFramework


class FrameworkRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, framework: AnalysisFramework) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO frameworks (
                company_name, stock_code, industry, sub_industry,
                business_description, keywords, competitors,
                macro_factors, monitoring_indicators, rss_feeds, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                framework.company_name,
                framework.stock_code,
                framework.industry,
                framework.sub_industry,
                framework.business_description,
                json.dumps(framework.keywords, ensure_ascii=False),
                json.dumps(framework.competitors, ensure_ascii=False),
                json.dumps(framework.macro_factors, ensure_ascii=False),
                json.dumps(framework.monitoring_indicators, ensure_ascii=False),
                json.dumps(framework.rss_feeds, ensure_ascii=False),
                1 if framework.is_active else 0,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_by_id(self, framework_id: int) -> AnalysisFramework | None:
        cursor = self.conn.execute("SELECT * FROM frameworks WHERE id = ?", (framework_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[AnalysisFramework]:
        cursor = self.conn.execute("SELECT * FROM frameworks ORDER BY created_at DESC")
        return [self._row_to_model(row) for row in cursor.fetchall()]

    def update(self, framework: AnalysisFramework) -> None:
        self.conn.execute(
            """
            UPDATE frameworks SET
                company_name=?, stock_code=?, industry=?, sub_industry=?,
                business_description=?, keywords=?, competitors=?,
                macro_factors=?, monitoring_indicators=?, rss_feeds=?,
                is_active=?, updated_at=?
            WHERE id=?
            """,
            (
                framework.company_name,
                framework.stock_code,
                framework.industry,
                framework.sub_industry,
                framework.business_description,
                json.dumps(framework.keywords, ensure_ascii=False),
                json.dumps(framework.competitors, ensure_ascii=False),
                json.dumps(framework.macro_factors, ensure_ascii=False),
                json.dumps(framework.monitoring_indicators, ensure_ascii=False),
                json.dumps(framework.rss_feeds, ensure_ascii=False),
                1 if framework.is_active else 0,
                datetime.now().isoformat(),
                framework.id,
            ),
        )
        self.conn.commit()

    def delete(self, framework_id: int) -> None:
        self.conn.execute("DELETE FROM frameworks WHERE id = ?", (framework_id,))
        self.conn.commit()

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> AnalysisFramework:
        is_active_val = row["is_active"] if "is_active" in row.keys() else 1
        return AnalysisFramework(
            id=row["id"],
            company_name=row["company_name"],
            stock_code=row["stock_code"],
            industry=row["industry"],
            sub_industry=row["sub_industry"],
            business_description=row["business_description"],
            keywords=json.loads(row["keywords"]),
            competitors=json.loads(row["competitors"]),
            macro_factors=json.loads(row["macro_factors"]),
            monitoring_indicators=json.loads(row["monitoring_indicators"]),
            rss_feeds=json.loads(row["rss_feeds"]),
            is_active=bool(is_active_val),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
