import json
import sqlite3
from datetime import datetime

from invest_research.data.database import init_db
from invest_research.data.framework_repo import FrameworkRepo
from invest_research.data.news_repo import NewsRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.data.analysis_repo import AnalysisRepo
from invest_research.models import (
    AnalysisFramework,
    InvestmentReport,
    NewsArticle,
    WeeklyAnalysis,
    NewsAnalysisItem,
    RiskItem,
    OpportunityItem,
)


def _create_test_framework(conn: sqlite3.Connection) -> int:
    repo = FrameworkRepo(conn)
    fw = AnalysisFramework(company_name="测试公司", stock_code="000001", keywords=["测试"])
    return repo.save(fw)


def test_database_migration():
    conn = init_db(db_path=":memory:")
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "frameworks" in tables
    assert "news_articles" in tables
    assert "analyses" in tables
    assert "reports" in tables
    conn.close()


def test_framework_repo_crud():
    conn = init_db(db_path=":memory:")
    repo = FrameworkRepo(conn)

    framework = AnalysisFramework(
        company_name="宁德时代",
        stock_code="300750",
        industry="新能源",
        sub_industry="动力电池",
        keywords=["宁德时代", "动力电池", "储能"],
        competitors=["比亚迪", "LG新能源"],
    )

    fid = repo.save(framework)
    assert fid > 0

    loaded = repo.get_by_id(fid)
    assert loaded is not None
    assert loaded.company_name == "宁德时代"
    assert loaded.keywords == ["宁德时代", "动力电池", "储能"]
    assert loaded.competitors == ["比亚迪", "LG新能源"]

    all_frameworks = repo.list_all()
    assert len(all_frameworks) == 1

    conn.close()


def test_news_repo_dedup():
    conn = init_db(db_path=":memory:")
    fid = _create_test_framework(conn)
    repo = NewsRepo(conn)

    article = NewsArticle(
        framework_id=fid,
        title="测试新闻",
        source="test",
        url="https://example.com/news/1",
        url_hash="abc123",
    )

    inserted = repo.insert_if_not_exists(article)
    assert inserted is True

    inserted_again = repo.insert_if_not_exists(article)
    assert inserted_again is False

    conn.close()


def test_analysis_repo():
    conn = init_db(db_path=":memory:")
    fid = _create_test_framework(conn)
    repo = AnalysisRepo(conn)

    analysis = WeeklyAnalysis(
        framework_id=fid,
        week_start=datetime(2025, 1, 1),
        week_end=datetime(2025, 1, 7),
        news_analyses=[
            NewsAnalysisItem(
                news_id=1,
                title="测试新闻",
                relevance="高",
                category="行业趋势",
                sentiment="利好",
                summary="测试摘要",
            )
        ],
        weekly_summary="本周行业向好",
    )

    aid = repo.save(analysis)
    assert aid > 0

    recent = repo.get_recent(fid, weeks=4)
    assert len(recent) == 1
    assert recent[0].weekly_summary == "本周行业向好"
    assert len(recent[0].news_analyses) == 1

    conn.close()


def test_report_repo():
    conn = init_db(db_path=":memory:")
    fid = _create_test_framework(conn)
    repo = ReportRepo(conn)

    report = InvestmentReport(
        framework_id=fid,
        report_date=datetime(2025, 1, 7),
        risks=[RiskItem(description="原材料涨价", severity="高", probability="中", impact="成本上升")],
        opportunities=[OpportunityItem(description="海外扩张", confidence="高", timeframe="中期", impact="收入增长")],
        investment_rating="推荐",
        rating_rationale="行业景气度高",
        executive_summary="总体向好",
    )

    rid = repo.save(report)
    assert rid > 0

    latest = repo.get_latest(fid)
    assert latest is not None
    assert latest.investment_rating == "推荐"
    assert len(latest.risks) == 1
    assert latest.risks[0].description == "原材料涨价"

    conn.close()


def test_model_serialization():
    framework = AnalysisFramework(
        company_name="测试公司",
        keywords=["关键词1", "关键词2"],
    )
    data = framework.model_dump()
    assert data["company_name"] == "测试公司"
    assert len(data["keywords"]) == 2

    restored = AnalysisFramework(**data)
    assert restored.company_name == framework.company_name
