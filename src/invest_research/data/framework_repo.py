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
                macro_factors, monitoring_indicators, rss_feeds,
                company_type, investment_strategy, analysis_dimensions, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                framework.company_type,
                framework.investment_strategy,
                json.dumps(framework.analysis_dimensions, ensure_ascii=False),
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
                company_type=?, investment_strategy=?, analysis_dimensions=?,
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
                framework.company_type,
                framework.investment_strategy,
                json.dumps(framework.analysis_dimensions, ensure_ascii=False),
                1 if framework.is_active else 0,
                datetime.now().isoformat(),
                framework.id,
            ),
        )
        self.conn.commit()

    def delete(self, framework_id: int) -> None:
        self.conn.execute("DELETE FROM frameworks WHERE id = ?", (framework_id,))
        self.conn.commit()

    def save_financial_cache(self, framework_id: int, summary: str) -> None:
        """保存财报缓存到数据库。"""
        self.conn.execute(
            """
            UPDATE frameworks SET
                financial_summary=?, financial_fetched_at=?
            WHERE id=?
            """,
            (summary, datetime.now().isoformat(), framework_id),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> AnalysisFramework:
        keys = row.keys()
        is_active_val = row["is_active"] if "is_active" in keys else 1
        financial_summary = row["financial_summary"] if "financial_summary" in keys else ""
        financial_fetched_at = row["financial_fetched_at"] if "financial_fetched_at" in keys else None
        company_type = row["company_type"] if "company_type" in keys else ""
        investment_strategy = row["investment_strategy"] if "investment_strategy" in keys else ""
        analysis_dims_raw = row["analysis_dimensions"] if "analysis_dimensions" in keys else "{}"
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
            company_type=company_type or "",
            investment_strategy=investment_strategy or "",
            analysis_dimensions=json.loads(analysis_dims_raw) if analysis_dims_raw else {},
            is_active=bool(is_active_val),
            financial_summary=financial_summary or "",
            financial_fetched_at=financial_fetched_at,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
