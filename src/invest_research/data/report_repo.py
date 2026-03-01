import json
import logging
import sqlite3
from datetime import datetime

from invest_research.models import InvestmentReport, RiskItem, OpportunityItem, NewsReference

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
                detailed_analysis, previous_rating, rating_change_reason,
                changes_from_previous
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                report.changes_from_previous,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_by_id(self, report_id: int) -> InvestmentReport | None:
        cursor = self.conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        return self._row_to_model(row) if row else None

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

    def delete(self, report_id: int) -> None:
        self.conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        self.conn.commit()

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
        risks_data = json.loads(row["risks"])
        risks = []
        for r in risks_data:
            r.setdefault("supporting_news", [])
            r["supporting_news"] = [NewsReference(**n) for n in r["supporting_news"]]
            risks.append(RiskItem(**r))

        opps_data = json.loads(row["opportunities"])
        opportunities = []
        for o in opps_data:
            o.setdefault("supporting_news", [])
            o["supporting_news"] = [NewsReference(**n) for n in o["supporting_news"]]
            opportunities.append(OpportunityItem(**o))

        changes_from_previous = ""
        try:
            changes_from_previous = row["changes_from_previous"] or ""
        except (IndexError, KeyError):
            pass

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
            changes_from_previous=changes_from_previous,
            created_at=row["created_at"],
        )
