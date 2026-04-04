from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # AI 后端切换：deepseek / anthropic
    ai_provider: str = "deepseek"

    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    newsapi_api_key: str = ""
    tavily_api_key: str = ""

    # DeepSeek 配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model_heavy: str = "deepseek-reasoner"
    deepseek_model_light: str = "deepseek-chat"

    # Claude 模型配置
    claude_model_heavy: str = "claude-opus-4-6"
    claude_model_light: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 4096
    claude_max_retries: int = 3

    # 爬虫配置
    crawl_polite_delay: float = 1.0
    crawl_random_delay_min: float = 2.0
    crawl_random_delay_max: float = 5.0
    newsapi_daily_limit: int = 100

    # 调度配置（统一周任务）
    schedule_weekly_day: str = "sat"
    schedule_weekly_hour: int = 8
    # 旧配置保留向后兼容（不再使用）
    schedule_crawl_day: str = "sun"
    schedule_crawl_hour: int = 20
    schedule_report_day: str = "mon"
    schedule_report_hour: int = 8

    # 分析配置
    analysis_rolling_weeks: int = 8
    analysis_weekly_summary_max_chars: int = 200

    # 去重配置
    dedup_title_similarity_threshold: float = 0.85

    # 路径配置
    data_dir: Path = Path("data")
    prompts_dir: Path = Path("config/prompts")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "invest_research.db"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
