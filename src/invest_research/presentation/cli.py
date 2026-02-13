import rich.box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from invest_research.models import AnalysisFramework

console = Console()


def display_ai_message(text: str) -> None:
    console.print(Panel(text, title="[bold cyan]AI 分析师[/]", border_style="cyan", box=rich.box.ROUNDED))


def get_user_input() -> str:
    return Prompt.ask("\n[bold green]你的回复[/]")


def display_framework(framework: AnalysisFramework) -> None:
    table = Table(title=f"分析框架: {framework.company_name}", box=rich.box.ROUNDED)
    table.add_column("字段", style="cyan", width=16)
    table.add_column("内容", style="white")

    table.add_row("公司名称", framework.company_name)
    table.add_row("股票代码", framework.stock_code)
    table.add_row("行业", framework.industry)
    table.add_row("细分领域", framework.sub_industry)
    table.add_row("主营业务", framework.business_description)
    table.add_row("关键词", ", ".join(framework.keywords))
    table.add_row("竞争对手", ", ".join(framework.competitors))
    table.add_row("宏观因素", ", ".join(framework.macro_factors))
    table.add_row("监控指标", ", ".join(framework.monitoring_indicators))
    table.add_row("RSS 源", "\n".join(framework.rss_feeds) if framework.rss_feeds else "无")

    console.print(table)


def display_frameworks_list(frameworks: list[AnalysisFramework]) -> None:
    if not frameworks:
        console.print("[yellow]暂无分析框架[/]")
        return

    table = Table(title="分析框架列表", box=rich.box.ROUNDED)
    table.add_column("ID", style="cyan", width=6)
    table.add_column("公司名称", style="white")
    table.add_column("行业", style="green")
    table.add_column("关键词数", style="yellow", justify="right")
    table.add_column("创建时间", style="dim")

    for fw in frameworks:
        table.add_row(
            str(fw.id),
            fw.company_name,
            fw.industry,
            str(len(fw.keywords)),
            str(fw.created_at)[:19] if fw.created_at else "",
        )

    console.print(table)


def display_success(message: str) -> None:
    console.print(f"[bold green]{message}[/]")


def display_error(message: str) -> None:
    console.print(f"[bold red]{message}[/]")


def display_info(message: str) -> None:
    console.print(f"[bold blue]{message}[/]")


def display_report_saved(path: str) -> None:
    console.print(Panel(
        f"报告已保存至: {path}",
        title="[bold green]报告生成完成[/]",
        border_style="green",
        box=rich.box.ROUNDED,
    ))
