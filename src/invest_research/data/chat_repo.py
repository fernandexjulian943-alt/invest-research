import json
import logging
import sqlite3
from datetime import datetime

from invest_research.models import ChatSession, ChatMessage

logger = logging.getLogger(__name__)


class ChatRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ===== Session =====

    def save_session(self, session: ChatSession) -> str:
        self.conn.execute(
            """
            INSERT INTO chat_sessions (id, framework_id, model_provider, created_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (session.id, session.framework_id, session.model_provider),
        )
        self.conn.commit()
        return session.id

    def get_session(self, session_id: str) -> ChatSession | None:
        cursor = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ChatSession(
            id=row["id"],
            framework_id=row["framework_id"],
            model_provider=row["model_provider"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update_session_provider(self, session_id: str, provider: str) -> None:
        self.conn.execute(
            "UPDATE chat_sessions SET model_provider = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (provider, session_id),
        )
        self.conn.commit()

    def list_sessions_by_framework(self, framework_id: int, limit: int = 20) -> list[ChatSession]:
        cursor = self.conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE framework_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (framework_id, limit),
        )
        return [
            ChatSession(
                id=row["id"],
                framework_id=row["framework_id"],
                model_provider=row["model_provider"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    def list_recent_frameworks(self, limit: int = 20) -> list[dict]:
        """获取有对话记录的股票，按最近对话时间排序去重。"""
        cursor = self.conn.execute(
            """
            SELECT
                f.id AS framework_id,
                f.company_name,
                f.stock_code,
                MAX(cs.updated_at) AS last_chat_at,
                COUNT(cs.id) AS session_count
            FROM chat_sessions cs
            JOIN frameworks f ON cs.framework_id = f.id
            GROUP BY f.id
            ORDER BY last_chat_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "framework_id": row["framework_id"],
                "company_name": row["company_name"],
                "stock_code": row["stock_code"],
                "last_chat_at": row["last_chat_at"],
                "session_count": row["session_count"],
            }
            for row in cursor.fetchall()
        ]

    def list_market_sessions(self, limit: int = 20) -> list[ChatSession]:
        """获取市场级对话（framework_id IS NULL）。"""
        cursor = self.conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE framework_id IS NULL
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [
            ChatSession(
                id=row["id"],
                framework_id=None,
                model_provider=row["model_provider"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in cursor.fetchall()
        ]

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        self.conn.commit()

    # ===== Message =====

    def save_message(self, msg: ChatMessage) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, specialist, data_refs)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                msg.session_id,
                msg.role,
                msg.content,
                msg.specialist,
                json.dumps(msg.data_refs, ensure_ascii=False),
            ),
        )
        # 同步更新 session 的 updated_at
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (msg.session_id,),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_messages(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        cursor = self.conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return [self._row_to_message(row) for row in cursor.fetchall()]

    def get_recent_messages(self, session_id: str, limit: int = 10) -> list[ChatMessage]:
        """获取最近 N 条消息（用于构建对话上下文）。"""
        cursor = self.conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ) sub ORDER BY created_at ASC
            """,
            (session_id, limit),
        )
        return [self._row_to_message(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> ChatMessage:
        data_refs = []
        try:
            raw = row["data_refs"]
            if raw:
                data_refs = json.loads(raw)
        except (json.JSONDecodeError, KeyError):
            pass
        return ChatMessage(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            specialist=row["specialist"] or "",
            data_refs=data_refs,
            created_at=row["created_at"],
        )
