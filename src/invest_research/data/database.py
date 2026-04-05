import sqlite3
from datetime import datetime
from pathlib import Path

from invest_research.config import get_settings

SCHEMA_VERSION = 13

MIGRATIONS = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS frameworks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            stock_code TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            sub_industry TEXT DEFAULT '',
            business_description TEXT DEFAULT '',
            keywords TEXT DEFAULT '[]',
            competitors TEXT DEFAULT '[]',
            macro_factors TEXT DEFAULT '[]',
            monitoring_indicators TEXT DEFAULT '[]',
            rss_feeds TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            source TEXT DEFAULT '',
            url TEXT DEFAULT '',
            url_hash TEXT DEFAULT '',
            content_snippet TEXT DEFAULT '',
            published_at TIMESTAMP,
            crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            relevance_score REAL DEFAULT 0.0,
            FOREIGN KEY (framework_id) REFERENCES frameworks(id),
            UNIQUE(url_hash)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id INTEGER NOT NULL,
            week_start TIMESTAMP NOT NULL,
            week_end TIMESTAMP NOT NULL,
            news_analyses TEXT DEFAULT '[]',
            weekly_summary TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (framework_id) REFERENCES frameworks(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id INTEGER NOT NULL,
            report_date TIMESTAMP NOT NULL,
            risks TEXT DEFAULT '[]',
            opportunities TEXT DEFAULT '[]',
            investment_rating TEXT DEFAULT '',
            rating_rationale TEXT DEFAULT '',
            executive_summary TEXT DEFAULT '',
            detailed_analysis TEXT DEFAULT '',
            previous_rating TEXT DEFAULT '',
            rating_change_reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (framework_id) REFERENCES frameworks(id)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_news_framework ON news_articles(framework_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_news_url_hash ON news_articles(url_hash);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_analyses_framework ON analyses(framework_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reports_framework ON reports(framework_id);
        """,
    ],
    2: [
        """
        ALTER TABLE frameworks ADD COLUMN is_active INTEGER DEFAULT 1;
        """,
    ],
    3: [
        """
        ALTER TABLE reports ADD COLUMN changes_from_previous TEXT DEFAULT '';
        """,
    ],
    4: [
        """
        ALTER TABLE frameworks ADD COLUMN financial_summary TEXT DEFAULT '';
        """,
        """
        ALTER TABLE frameworks ADD COLUMN financial_fetched_at TIMESTAMP DEFAULT NULL;
        """,
    ],
    5: [
        """
        ALTER TABLE frameworks ADD COLUMN company_type TEXT DEFAULT '';
        """,
        """
        ALTER TABLE frameworks ADD COLUMN analysis_dimensions TEXT DEFAULT '{}';
        """,
    ],
    6: [
        """
        ALTER TABLE frameworks ADD COLUMN investment_strategy TEXT DEFAULT '';
        """,
    ],
    7: [
        """
        ALTER TABLE reports ADD COLUMN signal_summary TEXT DEFAULT '';
        """,
    ],
    8: [
        """
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            report_id INTEGER,
            situation TEXT DEFAULT '',
            prediction TEXT DEFAULT '',
            actual_outcome TEXT DEFAULT '',
            was_correct INTEGER DEFAULT 0,
            reflection TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (framework_id) REFERENCES frameworks(id)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_reflections_framework_role ON reflections(framework_id, role);
        """,
    ],
    9: [
        """
        ALTER TABLE reports ADD COLUMN debate_detail TEXT DEFAULT '{}';
        """,
        """
        ALTER TABLE reports ADD COLUMN technical_detail TEXT DEFAULT '{}';
        """,
    ],
    10: [
        """
        ALTER TABLE reports ADD COLUMN financial_detail TEXT DEFAULT '';
        """,
        """
        ALTER TABLE reports ADD COLUMN news_detail TEXT DEFAULT '';
        """,
        """
        ALTER TABLE reports ADD COLUMN xueqiu_detail TEXT DEFAULT '';
        """,
    ],
    11: [
        """
        ALTER TABLE reports ADD COLUMN analyst_signals TEXT DEFAULT '';
        """,
    ],
    12: [
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            framework_id INTEGER NOT NULL,
            model_provider TEXT DEFAULT 'deepseek',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (framework_id) REFERENCES frameworks(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            specialist TEXT DEFAULT '',
            data_refs TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_framework ON chat_sessions(framework_id);
        """,
    ],
    13: [
        # chat_sessions: framework_id 改为可选（支持市场级对话）
        # SQLite 不支持 ALTER COLUMN，需要重建表
        """
        CREATE TABLE IF NOT EXISTS chat_sessions_v2 (
            id TEXT PRIMARY KEY,
            framework_id INTEGER DEFAULT NULL,
            model_provider TEXT DEFAULT 'deepseek',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (framework_id) REFERENCES frameworks(id)
        );
        """,
        """
        INSERT OR IGNORE INTO chat_sessions_v2 (id, framework_id, model_provider, created_at, updated_at)
        SELECT id, framework_id, model_provider, created_at, updated_at FROM chat_sessions;
        """,
        """
        DROP TABLE IF EXISTS chat_sessions;
        """,
        """
        ALTER TABLE chat_sessions_v2 RENAME TO chat_sessions;
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_framework ON chat_sessions(framework_id);
        """,
    ],
}


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        settings = get_settings()
        settings.ensure_dirs()
        db_path = settings.db_path
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_current_version(conn: sqlite3.Connection) -> int:
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        return row[0] if row and row[0] else 0
    except sqlite3.OperationalError:
        return 0


def migrate(conn: sqlite3.Connection) -> None:
    current = get_current_version(conn)
    for version in range(current + 1, SCHEMA_VERSION + 1):
        if version in MIGRATIONS:
            # 涉及表重建的迁移需要关闭 FK 检查（DROP TABLE 会触发 FK 约束）
            if version in _FK_OFF_MIGRATIONS:
                conn.execute("PRAGMA foreign_keys=OFF")
            for sql in MIGRATIONS[version]:
                conn.execute(sql)
            if version in _FK_OFF_MIGRATIONS:
                conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


# 需要关闭 FK 检查的迁移版本（涉及 DROP TABLE + RENAME 重建）
_FK_OFF_MIGRATIONS = {13}


def backup_db(db_path: Path | None = None, max_backups: int = 10) -> str | None:
    """服务启动时自动备份数据库。返回备份文件路径，跳过则返回 None。"""
    if db_path is None:
        settings = get_settings()
        db_path = settings.db_path

    if not db_path.exists():
        return None

    # 检查是否空库（frameworks 表 0 条），空库不备份
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        count = conn.execute("SELECT COUNT(*) FROM frameworks").fetchone()[0]
        conn.close()
        if count == 0:
            return None
    except Exception:
        return None

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"invest_research_{timestamp}.db"

    # SQLite 在线备份（WAL 模式安全）
    src = sqlite3.connect(str(db_path), timeout=5)
    dst = sqlite3.connect(str(backup_path))
    src.backup(dst)
    dst.close()
    src.close()

    # 清理旧备份，保留最近 max_backups 个
    backups = sorted(backup_dir.glob("invest_research_*.db"))
    for old in backups[:-max_backups]:
        old.unlink()

    return str(backup_path)


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    migrate(conn)
    return conn
