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
    company_type: str = ""  # consumer/tech/finance/manufacturing/pharma/energy/general
    investment_strategy: str = ""  # high_dividend / high_growth / balanced
    analysis_dimensions: dict = Field(default_factory=dict)  # 专业分析维度（JSON）
    is_active: bool = True
    financial_summary: str = ""
    financial_fetched_at: datetime | None = None
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
    impact: str = ""  # 重大/一般/轻微
    timeframe: str = ""  # 短期事件/中期趋势/长期结构性
    summary: str = ""


class WeeklyAnalysis(BaseModel):
    id: int | None = None
    framework_id: int
    week_start: datetime
    week_end: datetime
    news_analyses: list[NewsAnalysisItem] = Field(default_factory=list)
    weekly_summary: str = ""
    signal: str = ""  # bullish/bearish/neutral
    confidence: float = 0.0  # 0.0~1.0
    created_at: datetime | None = None


class NewsReference(BaseModel):
    title: str
    url: str


class RiskItem(BaseModel):
    description: str
    severity: str  # 高/中/低
    probability: str  # 高/中/低
    impact: str = ""
    source: str = ""  # 新闻/财报/情绪/多源交叉
    supporting_news: list[NewsReference] = Field(default_factory=list)


class OpportunityItem(BaseModel):
    description: str
    confidence: str  # 高/中/低
    timeframe: str = ""
    impact: str = ""
    source: str = ""  # 新闻/财报/情绪/多源交叉
    supporting_news: list[NewsReference] = Field(default_factory=list)


class Reflection(BaseModel):
    id: int | None = None
    framework_id: int
    role: str  # bull/bear/financial/news/technical/risk_advisor
    report_id: int | None = None
    situation: str = ""  # 当时的市场情况摘要
    prediction: str = ""  # 当时的预测
    actual_outcome: str = ""  # 实际结果
    was_correct: bool = False
    reflection: str = ""  # LLM 生成的反思
    created_at: datetime | None = None


class AnalystSignal(BaseModel):
    """各路分析师的标准化信号。"""
    signal: str = "neutral"  # bullish/bearish/neutral
    confidence: float = 0.0  # 0.0~1.0


class AnalystSignals(BaseModel):
    """五路分析师标准化信号汇总。"""
    news: AnalystSignal = Field(default_factory=AnalystSignal)
    financial: AnalystSignal = Field(default_factory=AnalystSignal)
    sentiment: AnalystSignal = Field(default_factory=AnalystSignal)
    technical: AnalystSignal = Field(default_factory=AnalystSignal)
    debate: AnalystSignal = Field(default_factory=AnalystSignal)


class SignalSummary(BaseModel):
    news_signal: str = ""
    financial_signal: str = ""
    sentiment_signal: str = ""
    technical_signal: str = ""
    debate_lean: str = ""  # 偏看多/偏看空/平衡
    consistency: str = ""  # 一致/部分一致/矛盾
    confidence: float = 0.0  # 0.0~1.0（旧数据可能是 str，反序列化时转换）
    conflicts: str = ""
    overall_signal: str = ""  # bullish/bearish/neutral
    overall_confidence: float = 0.0  # 0.0~1.0


class InvestmentReport(BaseModel):
    id: int | None = None
    framework_id: int
    report_date: datetime
    signal_summary: SignalSummary | None = None
    analyst_signals: AnalystSignals | None = None
    risks: list[RiskItem] = Field(default_factory=list)
    opportunities: list[OpportunityItem] = Field(default_factory=list)
    investment_rating: str = ""  # 强烈推荐/推荐/中性/谨慎/回避
    rating_rationale: str = ""
    executive_summary: str = ""
    detailed_analysis: str = ""
    previous_rating: str = ""
    rating_change_reason: str = ""
    changes_from_previous: str = ""
    debate_detail: dict = Field(default_factory=dict)
    technical_detail: dict = Field(default_factory=dict)
    financial_detail: str = ""
    news_detail: str = ""
    xueqiu_detail: str = ""
    created_at: datetime | None = None


# ===== 对话系统模型 =====


class ChatMessage(BaseModel):
    id: int | None = None
    session_id: str
    role: str  # user / assistant / system
    content: str
    specialist: str = ""  # general/financial/quant/sentiment/debate/competitor
    data_refs: list[str] = Field(default_factory=list)  # 引用的数据来源标识
    created_at: datetime | None = None


class ChatSession(BaseModel):
    id: str  # UUID
    framework_id: int | None = None  # None = 市场级对话（不绑定具体股票）
    model_provider: str = "deepseek"  # deepseek / anthropic
    created_at: datetime | None = None
    updated_at: datetime | None = None
