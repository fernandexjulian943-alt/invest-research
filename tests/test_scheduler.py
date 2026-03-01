from unittest.mock import MagicMock, patch

from invest_research.models import AnalysisFramework, InvestmentReport, WeeklyAnalysis
from invest_research.scheduler.jobs import run_weekly_research_job, create_scheduler


def _make_framework(name: str, stock_code: str = "000001", is_active: bool = True) -> AnalysisFramework:
    return AnalysisFramework(
        id=1, company_name=name, stock_code=stock_code,
        is_active=is_active, keywords=["测试"],
    )


@patch("invest_research.scheduler.jobs.init_db")
@patch("invest_research.scheduler.jobs.FrameworkRepo")
@patch("invest_research.scheduler.jobs.NewsRepo")
@patch("invest_research.scheduler.jobs.AnalysisRepo")
@patch("invest_research.scheduler.jobs.ReportRepo")
@patch("invest_research.scheduler.jobs.ClaudeClient")
@patch("invest_research.scheduler.jobs.CrawlService")
@patch("invest_research.scheduler.jobs.FinancialDataService")
@patch("invest_research.scheduler.jobs.AnalysisService")
@patch("invest_research.scheduler.jobs.ReportService")
@patch("invest_research.scheduler.jobs.save_report")
def test_should_run_full_pipeline_when_active_frameworks_exist(
    mock_save_report, mock_report_svc_cls, mock_analysis_svc_cls,
    mock_financial_cls, mock_crawl_cls, mock_claude_cls,
    mock_report_repo, mock_analysis_repo, mock_news_repo,
    mock_framework_repo, mock_init_db,
):
    fw = _make_framework("测试公司", "600519")
    mock_conn = MagicMock()
    mock_init_db.return_value = mock_conn
    mock_framework_repo.return_value.list_all.return_value = [fw]

    mock_crawl = mock_crawl_cls.return_value
    mock_crawl.crawl_all.return_value = 5

    mock_financial = mock_financial_cls.return_value
    mock_financial.fetch_summary.return_value = "财务摘要"

    mock_analysis = mock_analysis_svc_cls.return_value
    mock_analysis.analyze_week.return_value = WeeklyAnalysis(
        framework_id=1,
        week_start=MagicMock(),
        week_end=MagicMock(),
        news_analyses=[],
        weekly_summary="测试总结",
    )

    mock_report = mock_report_svc_cls.return_value
    mock_report.generate_report.return_value = InvestmentReport(
        framework_id=1, report_date=MagicMock(),
        investment_rating="推荐",
    )

    run_weekly_research_job()

    mock_crawl.crawl_all.assert_called_once_with(fw)
    mock_financial.fetch_summary.assert_called_once_with("600519")
    mock_analysis.analyze_week.assert_called_once_with(fw, financial_context="财务摘要")
    mock_report.generate_report.assert_called_once_with(fw, financial_context="财务摘要")
    mock_save_report.assert_called_once()
    mock_conn.close.assert_called_once()


@patch("invest_research.scheduler.jobs.init_db")
@patch("invest_research.scheduler.jobs.FrameworkRepo")
def test_should_skip_when_no_active_frameworks(mock_framework_repo, mock_init_db):
    inactive_fw = _make_framework("停用公司", is_active=False)
    mock_conn = MagicMock()
    mock_init_db.return_value = mock_conn
    mock_framework_repo.return_value.list_all.return_value = [inactive_fw]

    run_weekly_research_job()

    mock_conn.close.assert_called_once()


@patch("invest_research.scheduler.jobs.init_db")
@patch("invest_research.scheduler.jobs.FrameworkRepo")
@patch("invest_research.scheduler.jobs.NewsRepo")
@patch("invest_research.scheduler.jobs.AnalysisRepo")
@patch("invest_research.scheduler.jobs.ReportRepo")
@patch("invest_research.scheduler.jobs.ClaudeClient")
@patch("invest_research.scheduler.jobs.CrawlService")
@patch("invest_research.scheduler.jobs.FinancialDataService")
@patch("invest_research.scheduler.jobs.AnalysisService")
@patch("invest_research.scheduler.jobs.ReportService")
@patch("invest_research.scheduler.jobs.save_report")
def test_should_continue_other_frameworks_when_one_fails(
    mock_save_report, mock_report_svc_cls, mock_analysis_svc_cls,
    mock_financial_cls, mock_crawl_cls, mock_claude_cls,
    mock_report_repo, mock_analysis_repo, mock_news_repo,
    mock_framework_repo, mock_init_db,
):
    fw_fail = _make_framework("失败公司")
    fw_fail.id = 1
    fw_ok = _make_framework("正常公司")
    fw_ok.id = 2

    mock_conn = MagicMock()
    mock_init_db.return_value = mock_conn
    mock_framework_repo.return_value.list_all.return_value = [fw_fail, fw_ok]

    call_count = 0

    def crawl_side_effect(fw):
        nonlocal call_count
        call_count += 1
        if fw.company_name == "失败公司":
            raise RuntimeError("爬取异常")
        return 3

    mock_crawl = mock_crawl_cls.return_value
    mock_crawl.crawl_all.side_effect = crawl_side_effect

    mock_financial = mock_financial_cls.return_value
    mock_financial.fetch_summary.return_value = ""

    mock_analysis = mock_analysis_svc_cls.return_value
    mock_analysis.analyze_week.return_value = WeeklyAnalysis(
        framework_id=2, week_start=MagicMock(), week_end=MagicMock(),
        news_analyses=[], weekly_summary="总结",
    )

    mock_report = mock_report_svc_cls.return_value
    mock_report.generate_report.return_value = InvestmentReport(
        framework_id=2, report_date=MagicMock(), investment_rating="中性",
    )

    run_weekly_research_job()

    # 两个框架都应被尝试
    assert call_count == 2
    # 第二个框架正常完成
    mock_save_report.assert_called_once()
    mock_conn.close.assert_called_once()


def test_should_create_scheduler_with_weekly_job():
    with patch("invest_research.scheduler.jobs.get_settings") as mock_settings:
        settings = MagicMock()
        settings.schedule_weekly_day = "sat"
        settings.schedule_weekly_hour = 8
        mock_settings.return_value = settings

        scheduler = create_scheduler()

    job = scheduler.get_job("weekly_research")
    assert job is not None
    assert job.func == run_weekly_research_job
