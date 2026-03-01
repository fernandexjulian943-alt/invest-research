from datetime import datetime
from pathlib import Path

from invest_research.config import get_settings
from invest_research.models import AnalysisFramework, InvestmentReport


RATING_EMOJI = {
    "强烈推荐": "🟢🟢",
    "推荐": "🟢",
    "中性": "🟡",
    "谨慎": "🟠",
    "回避": "🔴",
}

SEVERITY_LABEL = {"高": "🔴", "中": "🟡", "低": "🟢"}


def render_report(
    report: InvestmentReport,
    framework: AnalysisFramework,
) -> str:
    rating_icon = RATING_EMOJI.get(report.investment_rating, "")
    report_date = report.report_date.strftime("%Y-%m-%d")

    lines = [
        f"# {framework.company_name} 投资研究报告",
        f"",
        f"**报告日期**: {report_date}",
        f"**行业**: {framework.industry} - {framework.sub_industry}",
        f"**股票代码**: {framework.stock_code}",
        f"",
        f"---",
        f"",
        f"## 投资评级: {rating_icon} {report.investment_rating}",
        f"",
    ]

    if report.previous_rating:
        if report.previous_rating != report.investment_rating:
            lines.append(f"**评级变动**: {report.previous_rating} → {report.investment_rating}")
        else:
            lines.append(f"**评级变动**: 维持 {report.investment_rating}")
        if report.rating_change_reason:
            lines.append(f"**变动原因**: {report.rating_change_reason}")
        lines.append("")

    lines.append(f"**评级理由**: {report.rating_rationale}")
    lines.append("")

    # 执行摘要
    lines.extend([
        "---",
        "",
        "## 执行摘要",
        "",
        report.executive_summary,
        "",
    ])

    # 风险评估
    if report.risks:
        lines.extend(["---", "", "## 风险评估", ""])
        lines.append("| 严重程度 | 概率 | 风险描述 | 影响 |")
        lines.append("|----------|------|----------|------|")
        for risk in report.risks:
            sev = SEVERITY_LABEL.get(risk.severity, risk.severity)
            lines.append(f"| {sev} {risk.severity} | {risk.probability} | {risk.description} | {risk.impact} |")
        lines.append("")

    # 机会识别
    if report.opportunities:
        lines.extend(["---", "", "## 机会识别", ""])
        lines.append("| 置信度 | 时间框架 | 机会描述 | 影响 |")
        lines.append("|--------|----------|----------|------|")
        for opp in report.opportunities:
            lines.append(f"| {opp.confidence} | {opp.timeframe} | {opp.description} | {opp.impact} |")
        lines.append("")

    # 详细分析
    if report.detailed_analysis:
        lines.extend([
            "---",
            "",
            "## 详细分析",
            "",
            report.detailed_analysis,
            "",
        ])

    # 与上期报告对比
    if report.changes_from_previous:
        lines.extend([
            "---",
            "",
            "## 与上期报告对比",
            "",
            report.changes_from_previous,
            "",
        ])

    # 参考新闻链接（汇总所有风险和机会的支撑新闻，去重后列出）
    seen_urls = set()
    all_news = []
    for risk in report.risks:
        for news in risk.supporting_news:
            if news.url and news.url not in seen_urls:
                seen_urls.add(news.url)
                all_news.append(news)
    for opp in report.opportunities:
        for news in opp.supporting_news:
            if news.url and news.url not in seen_urls:
                seen_urls.add(news.url)
                all_news.append(news)

    if all_news:
        lines.extend(["---", "", "## 参考新闻链接", ""])
        for i, news in enumerate(all_news, 1):
            lines.append(f"{i}. {news.title}")
            lines.append(f"   {news.url}")
        lines.append("")

    # 尾注
    lines.extend([
        "---",
        "",
        f"*本报告由 AI 投研分析系统自动生成，仅供参考，不构成投资建议。*",
        f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])

    return "\n".join(lines)


def save_report(
    report: InvestmentReport,
    framework: AnalysisFramework,
) -> str:
    settings = get_settings()
    settings.ensure_dirs()

    content = render_report(report, framework)
    date_str = report.report_date.strftime("%Y-%m-%d")
    filename = f"{date_str}_{framework.company_name}.md"
    filepath = settings.reports_dir / filename
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
