from datetime import datetime

from pydantic import BaseModel, Field


class AnalysisFramework(BaseModel):
    id: int | None = None
    company_name: str
    stock_code: str = ""
    industry: str = ""
    sub_industry: str = ""
    business_description: str = ""
    keywords: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    macro_factors: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)
    rss_feeds: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NewsArticle(BaseModel):
    id: int | None = None
    framework_id: int
    title: str
    source: str
    url: str
    url_hash: str = ""
    content_snippet: str = ""
    published_at: datetime | None = None
    crawled_at: datetime | None = None
    relevance_score: float = 0.0


class NewsAnalysisItem(BaseModel):
    news_id: int
    title: str
    relevance: str = ""
    category: str = ""
    sentiment: str = ""
    summary: str = ""


class WeeklyAnalysis(BaseModel):
    id: int | None = None
    framework_id: int
    week_start: datetime
    week_end: datetime
    news_analyses: list[NewsAnalysisItem] = Field(default_factory=list)
    weekly_summary: str = ""
    created_at: datetime | None = None


class NewsReference(BaseModel):
    title: str
    url: str


class RiskItem(BaseModel):
    description: str
    severity: str  # 高/中/低
    probability: str  # 高/中/低
    impact: str = ""
    supporting_news: list[NewsReference] = Field(default_factory=list)


class OpportunityItem(BaseModel):
    description: str
    confidence: str  # 高/中/低
    timeframe: str = ""
    impact: str = ""
    supporting_news: list[NewsReference] = Field(default_factory=list)


class InvestmentReport(BaseModel):
    id: int | None = None
    framework_id: int
    report_date: datetime
    risks: list[RiskItem] = Field(default_factory=list)
    opportunities: list[OpportunityItem] = Field(default_factory=list)
    investment_rating: str = ""  # 强烈推荐/推荐/中性/谨慎/回避
    rating_rationale: str = ""
    executive_summary: str = ""
    detailed_analysis: str = ""
    previous_rating: str = ""
    rating_change_reason: str = ""
    changes_from_previous: str = ""
    created_at: datetime | None = None
