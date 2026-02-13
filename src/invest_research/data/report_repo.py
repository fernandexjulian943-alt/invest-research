import json
import logging
import sqlite3
from datetime import datetime

from invest_research.models import InvestmentReport, RiskItem, OpportunityItem

logger = logging.getLogger(__name__)


class ReportRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, report: InvestmentReport) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO reports (
                framework_id, report_date, risks, opportunities,
                investment_rating, rating_rationale, executive_summary,
                detailed_analysis, previous_rating, rating_change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.framework_id,
                report.report_date.isoformat(),
                json.dumps([r.model_dump() for r in report.risks], ensure_ascii=False),
                json.dumps([o.model_dump() for o in report.opportunities], ensure_ascii=False),
                report.investment_rating,
                report.rating_rationale,
                report.executive_summary,
                report.detailed_analysis,
                report.previous_rating,
                report.rating_change_reason,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest(self, framework_id: int) -> InvestmentReport | None:
        cursor = self.conn.execute(
            """
            SELECT * FROM reports
            WHERE framework_id = ?
            ORDER BY report_date DESC
            LIMIT 1
            """,
            (framework_id,),
        )
        row = cursor.fetchone()
        return self._row_to_model(row) if row else None

    def get_by_framework(self, framework_id: int, limit: int = 10) -> list[InvestmentReport]:
        cursor = self.conn.execute(
            """
            SELECT * FROM reports
            WHERE framework_id = ?
            ORDER BY report_date DESC
            LIMIT ?
            """,
            (framework_id, limit),
        )
        return [self._row_to_model(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> InvestmentReport:
        risks = [RiskItem(**r) for r in json.loads(row["risks"])]
        opportunities = [OpportunityItem(**o) for o in json.loads(row["opportunities"])]

        return InvestmentReport(
            id=row["id"],
            framework_id=row["framework_id"],
            report_date=datetime.fromisoformat(row["report_date"]),
            risks=risks,
            opportunities=opportunities,
            investment_rating=row["investment_rating"],
            rating_rationale=row["rating_rationale"],
            executive_summary=row["executive_summary"],
            detailed_analysis=row["detailed_analysis"],
            previous_rating=row["previous_rating"],
            rating_change_reason=row["rating_change_reason"],
            created_at=row["created_at"],
        )
