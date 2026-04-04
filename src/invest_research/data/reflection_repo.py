import sqlite3
from datetime import datetime

from invest_research.models import Reflection


class ReflectionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, r: Reflection) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO reflections (
                framework_id, role, report_id, situation,
                prediction, actual_outcome, was_correct, reflection
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.framework_id, r.role, r.report_id, r.situation,
                r.prediction, r.actual_outcome, int(r.was_correct), r.reflection,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_by_framework_and_role(
        self, framework_id: int, role: str, limit: int = 5
    ) -> list[Reflection]:
        """获取某只股票某个角色的最近反思。"""
        cursor = self.conn.execute(
            """
            SELECT * FROM reflections
            WHERE framework_id = ? AND role = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (framework_id, role, limit),
        )
        return [self._row_to_model(row) for row in cursor.fetchall()]

    def get_by_industry_and_role(
        self, industry: str, role: str, limit: int = 3
    ) -> list[Reflection]:
        """跨股票检索同行业的反思（迁移学习）。"""
        cursor = self.conn.execute(
            """
            SELECT r.* FROM reflections r
            JOIN frameworks f ON r.framework_id = f.id
            WHERE f.industry = ? AND r.role = ?
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (industry, role, limit),
        )
        return [self._row_to_model(row) for row in cursor.fetchall()]

    def exists_for_report(self, report_id: int) -> bool:
        """检查某份报告是否已经做过反思。"""
        cursor = self.conn.execute(
            "SELECT 1 FROM reflections WHERE report_id = ? LIMIT 1",
            (report_id,),
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> Reflection:
        return Reflection(
            id=row["id"],
            framework_id=row["framework_id"],
            role=row["role"],
            report_id=row["report_id"],
            situation=row["situation"],
            prediction=row["prediction"],
            actual_outcome=row["actual_outcome"],
            was_correct=bool(row["was_correct"]),
            reflection=row["reflection"],
            created_at=row["created_at"],
        )
