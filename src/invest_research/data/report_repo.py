import json
import logging
import sqlite3
from datetime import datetime

from invest_research.models import InvestmentReport, SignalSummary, AnalystSignals, RiskItem, OpportunityItem, NewsReference

logger = logging.getLogger(__name__)


class ReportRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, report: InvestmentReport) -> int:
        signal_json = ""
        if report.signal_summary:
            signal_json = json.dumps(report.signal_summary.model_dump(), ensure_ascii=False)
        analyst_signals_json = ""
        if report.analyst_signals:
            analyst_signals_json = json.dumps(report.analyst_signals.model_dump(), ensure_ascii=False)
        cursor = self.conn.execute(
            """
            INSERT INTO reports (
                framework_id, report_date, risks, opportunities,
                investment_rating, rating_rationale, executive_summary,
                detailed_analysis, previous_rating, rating_change_reason,
                changes_from_previous, signal_summary,
                debate_detail, technical_detail,
                financial_detail, news_detail, xueqiu_detail,
                analyst_signals
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                signal_json,
                json.dumps(report.debate_detail, ensure_ascii=False) if report.debate_detail else "{}",
                json.dumps(report.technical_detail, ensure_ascii=False) if report.technical_detail else "{}",
                report.financial_detail or "",
                report.news_detail or "",
                report.xueqiu_detail or "",
                analyst_signals_json,
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

        signal_summary = None
        try:
            raw = row["signal_summary"]
            if raw:
                data = json.loads(raw)
                # 兼容旧数据：confidence 从 "高/中/低" 转 float
                conf = data.get("confidence", 0.0)
                if isinstance(conf, str):
                    conf_map = {"高": 0.8, "中": 0.5, "低": 0.2}
                    data["confidence"] = conf_map.get(conf, 0.0)
                signal_summary = SignalSummary(**data)
        except (IndexError, KeyError):
            pass

        analyst_signals = None
        try:
            raw = row["analyst_signals"]
            if raw:
                analyst_signals = AnalystSignals(**json.loads(raw))
        except (IndexError, KeyError):
            pass

        debate_detail = {}
        try:
            raw = row["debate_detail"]
            if raw:
                debate_detail = json.loads(raw)
        except (IndexError, KeyError):
            pass

        technical_detail = {}
        try:
            raw = row["technical_detail"]
            if raw:
                technical_detail = json.loads(raw)
        except (IndexError, KeyError):
            pass

        return InvestmentReport(
            id=row["id"],
            framework_id=row["framework_id"],
            report_date=datetime.fromisoformat(row["report_date"]),
            signal_summary=signal_summary,
            analyst_signals=analyst_signals,
            risks=risks,
            opportunities=opportunities,
            investment_rating=row["investment_rating"],
            rating_rationale=row["rating_rationale"],
            executive_summary=row["executive_summary"],
            detailed_analysis=row["detailed_analysis"],
            previous_rating=row["previous_rating"],
            rating_change_reason=row["rating_change_reason"],
            changes_from_previous=changes_from_previous,
            debate_detail=debate_detail,
            technical_detail=technical_detail,
            financial_detail=row["financial_detail"] if "financial_detail" in row.keys() else "",
            news_detail=row["news_detail"] if "news_detail" in row.keys() else "",
            xueqiu_detail=row["xueqiu_detail"] if "xueqiu_detail" in row.keys() else "",
            created_at=row["created_at"],
        )
