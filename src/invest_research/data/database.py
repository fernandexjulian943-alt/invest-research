import sqlite3
from pathlib import Path

from invest_research.config import get_settings

SCHEMA_VERSION = 3

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
            for sql in MIGRATIONS[version]:
                conn.execute(sql)
            conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    migrate(conn)
    return conn
