# 项目进度

## 已完成

### 交互式投研分析（计划: ~/.claude/plans/snazzy-jingling-turtle.md）
- 新增「新建研究」tab：交互模式（分步对话）+ 快速模式（全自动）
- 交互流程：输入股票→公司概览→AI策略草案→用户编辑确认→自动 crawl→analyze→report
- 专业框架：`framework_builder_pro.md` 按行业适配分析维度（consumer/tech/finance/manufacturing/pharma/energy/realestate/general）
- 新增字段：AnalysisFramework.company_type + analysis_dimensions（数据库 schema v5）
- 新增 API：POST /api/research/interactive、GET /api/research/{task_id}/status、POST /api/research/{task_id}/confirm-strategy
- 下游 prompt 适配：news_analyst.md 和 risk_advisor.md 传入 analysis_dimensions 上下文
- 旧模式（POST /api/research）完全兼容不变

### 投资报告优化（计划: ~/.claude/plans/cached-herding-abelson.md）
- 风险/机会附带支撑新闻链接
- 增量新闻抓取 + 与上期报告差异对比
- 数据库迁移 v3

### 关注股票管理 v1（计划: ~/.claude/plans/eventual-percolating-charm.md）
- Tab 改名「框架管理」→「关注股票管理」
- 左右双栏 flex 布局（左栏股票列表 flex:2，右栏财报面板 flex:3）
- `GET /api/frameworks` 返回增加 stock_code 字段
- `GET /api/frameworks/{id}/financial` 新端点，调用 FinancialDataService
- 点击股票行高亮 + 右栏展示财报摘要
- 停用/启用按钮通过 event.stopPropagation() 隔离

### 股票数据查询服务（计划: ~/.claude/plans/fluttering-seeking-acorn.md）
- 新增「股票数据查询」tab，含实时报价、历史价格、公司财报 3 个搜索卡片
- 新增 3 个独立 API 端点（不依赖 framework_id，按代码直接查询）
- 抽取 `market_utils.py` 共享工具模块，`financial_service.py` 复用
- OpenClaw 插件: `static/openclaw_plugin.js`

### 智能股票输入解析
- 支持中文公司名称输入（如「英伟达」→ NVDA、「贵州茅台」→ 600519、「腾讯」→ 00700）
- 港股短代码自动补零（如 `700` / `0700` → `00700`）
- 三层解析链路：标准代码检测 → 框架DB名称匹配 → AKShare名称搜索
- AKShare名称搜索覆盖：A股全量（5000+只）、美股热门（~30只）、港股热门（~100只），进程级缓存
- 所有 3 个股票查询 API 端点均支持智能解析

### 雪球 Token 自动刷新
- 新增 `xq_token_manager.py` 模块，封装所有雪球 API 调用
- 自动检测 token 过期（捕获 `KeyError`），通过 Playwright 无头浏览器访问雪球页面刷新 `xq_a_token` cookie
- 惰性刷新策略：仅在 API 调用实际失败时触发，非定时轮询
- `threading.Lock` 防止并发请求同时触发多次浏览器刷新
- 三层容错：缓存 token → Playwright 刷新重试 → 回退 AKShare 默认 token
- 受影响调用点：`stock_quote_service.py`（实时行情）、`stock_history_service.py`（美股交易所前缀解析）

### 雪球大V观点分析
- 新增 `services/xueqiu_analysis.py`：Playwright 抓取雪球股票讨论页帖子
- 反检测绕过阿里云 WAF：`--disable-blink-features=AutomationControlled` + 隐藏 webdriver 属性
- 策略：先访问股票详情页通过 WAF 挑战，再在页面上下文内 fetch 调用帖子 JSON API
- 新增 `GET /api/stock/xueqiu-analysis?code={代码}` 端点，支持智能解析
- 报告弹窗新增「雪球大V观点」按钮，点击异步加载帖子列表
- 帖子按粉丝数+互动量排序，展示用户名、粉丝数、帖子标题（可点击跳转原文）、发布时间

### 投研 Prompt 体系全面升级（2026-04-02）
- 三路分析 prompt 重写（news/financial/xueqiu_analyst.md）+ Financial CoT 思维链
- 综合报告 prompt 改造（risk_advisor.md → 五路交叉验证 + 信号摘要 + 辩论裁决）
- 技术面分析（technical_analyst.md + TechnicalAnalysisService）
- Bull/Bear 辩论（bull/bear_researcher.md + DebateService）
- 反思记忆系统（reflector.md + ReflectionService + ReflectionRepo + SQLite 持久化）
- 数据库迁移 v6→v8（signal_summary 字段 + reflections 表）
- 输出标准化 v11（analyst_signals 字段 + signal/confidence 统一）

### P0 输出标准化（2026-04-02）
- 各 analyst 统一输出 `signal`(bullish/bearish/neutral) + `confidence`(0.0~1.0)
- 4 个 prompt 加标准化字段（news/financial/xueqiu/technical_analyst.md）
- 4 个 service 解析并传递信号（format_for_report 追加信号行）
- DebateService 从 bull/bear 论述力度做启发式信号推断
- models.py 新增 AnalystSignal/AnalystSignals 模型，SignalSummary.confidence 改 float
- pipeline 收集五路信号构建 AnalystSignals，传给 report_service
- risk_advisor.md 适配：接收标准化信号输入，输出 overall_signal + overall_confidence
- 数据库迁移 v11：reports 表新增 analyst_signals 列
- 旧数据兼容：SignalSummary.confidence "高/中/低" 自动映射为 0.8/0.5/0.2

### 对话式投研助手 Phase 1（2026-04-03）
- 新增「投研对话」Tab：选股票 → 自然语言问答 → 多角色专家回答
- 架构：Intent Router（规则+LLM）→ Context Assembler（按角色取数据）→ Specialist Agent（流式回答）
- 6 个专家角色：综合顾问/财务分析师/量化分析师/情绪分析师/多空辩手/竞品分析师（占位）
- 6 个对话 prompt：`config/prompts/chat_*.md`
- 数据库迁移 v12：chat_sessions + chat_messages 表
- 新增 6 个 API：POST/GET/DELETE chat sessions, POST messages(SSE), PUT provider, GET sessions by framework
- 前端：对话气泡、角色标签、模型切换（Claude/DeepSeek）、快捷问题、过时数据警告
- 流式输出：Anthropic 和 DeepSeek 双通道原生 streaming
- 上下文组装：按角色按需注入本地数据（报告/财务/技术/情绪/辩论），数据新鲜度检查
- 对话历史自动压缩：参考 Claude Code 机制，超过 12 条/3000 token 时，早期消息 LLM 摘要化，近期 6 条保留原文
- 新增文件：chat_service.py, intent_router.py, context_assembler.py, context_compressor.py, chat_repo.py, models.py(+ChatSession/ChatMessage)

### 对话系统 Phase 2 改进（2026-04-04）
- 左边栏改为"最近对话股票"：按最近对话时间排序去重，点击直接查看历史对话
- 新增 API：`GET /api/chat/recent-stocks` — 从 chat_sessions JOIN frameworks 查询
- 新对话入口：顶部 "+ 新对话"按钮，展开搜索框+全部关注股票列表
- 选股行为改变：选中已有对话的股票默认打开最近一次对话（非创建新会话）
- ContextAssembler 自动注入实时行情：调用 StockQuoteService 获取现价/PE/PB/股息率/市值等
- 财务角色自动刷新：financial_summary 缺失或过期时自动调用 FinancialDataService 实时获取
- 6 个对话 prompt 增加数据使用原则：优先使用已提供数据直接回答，不让用户自己去查

### 对话系统 Phase 3：两轮架构 + 按需补数据（2026-04-04）
- 两轮对话架构：Pass 1（轻量 LLM 分析数据需求）→ 按需拉取 → Pass 2（正式回答）
- 全程流式输出：routing → analyzing → fetching → fetched → meta → text → done（无空白等待）
- 新增 `data_fetcher.py`：统一调度 8 类数据源（行情/财报/分红/技术/情绪/新闻/辩论/反思）
- 新增 `data_needs.md` prompt：数据需求分析（判断回答问题需要补哪些数据）
- ContextAssembler 新增 `build_data_inventory()`（数据目录：有/缺/新鲜度）+ `assemble_with_extra()`（合并额外数据）
- 数据拉取后写入长期记忆（financial_summary → framework 表）
- 前端实时状态：角色名 + spinner + 数据补充进度打勾

## 待做

### 对话系统 Phase 4
- 对话导出 + 对话内触发重新研究
- 更多专家角色细化 + OpenClaw skill 集成

### P2-1 DCF 估值模块
- 参考 ai-hedge-fund，给出定量"贵/便宜/合理"锚点

## 数据架构

### 整体分层

```
表现层 (presentation/)     ← FastAPI 路由 + 前端页面
    ↓
服务层 (services/)         ← 业务逻辑、外部API调用（Claude AI、AKShare）
    ↓
数据访问层 (data/)         ← Repository 模式，SQLite 读写
    ↓
数据库 (SQLite, WAL 模式)  ← schema_version=11，5 张业务表
```

依赖方向单向：表现层 → 服务层 → 数据访问层。服务层不直接操作 SQL，数据层不包含业务逻辑。

### 数据库表结构（SQLite, schema v12）

#### frameworks — 分析框架（关注股票）
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| company_name | TEXT NOT NULL | 公司名称 |
| stock_code | TEXT | 股票代码 |
| industry / sub_industry | TEXT | 行业分类 |
| business_description | TEXT | 业务描述 |
| keywords | TEXT (JSON) | 搜索关键词数组 |
| competitors | TEXT (JSON) | 竞争对手数组 |
| macro_factors | TEXT (JSON) | 宏观因素数组 |
| monitoring_indicators | TEXT (JSON) | 监控指标数组 |
| rss_feeds | TEXT (JSON) | RSS 源数组 |
| is_active | INTEGER | 是否启用周报监控（v2 新增） |
| created_at / updated_at | TIMESTAMP | 时间戳 |

#### news_articles — 抓取的新闻
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| framework_id | INTEGER FK | 关联 frameworks |
| title | TEXT NOT NULL | 标题 |
| source / url | TEXT | 来源与链接 |
| url_hash | TEXT UNIQUE | URL 的 SHA256，用于去重 |
| content_snippet | TEXT | 正文摘要 |
| published_at / crawled_at | TIMESTAMP | 发布/抓取时间 |
| relevance_score | REAL | AI 相关性评分 |

索引: `idx_news_framework`, `idx_news_url_hash`

#### analyses — 周度 AI 分析
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| framework_id | INTEGER FK | 关联 frameworks |
| week_start / week_end | TIMESTAMP | 分析周期 |
| news_analyses | TEXT (JSON) | NewsAnalysisItem 数组（每条新闻的分类/情感/摘要） |
| weekly_summary | TEXT | AI 生成的周度总结 |

索引: `idx_analyses_framework`

#### reports — 投资研究报告
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| framework_id | INTEGER FK | 关联 frameworks |
| report_date | TIMESTAMP | 报告日期 |
| risks | TEXT (JSON) | RiskItem 数组（含 supporting_news） |
| opportunities | TEXT (JSON) | OpportunityItem 数组（含 supporting_news） |
| investment_rating | TEXT | 评级: 强烈推荐/推荐/中性/谨慎/回避 |
| rating_rationale | TEXT | 评级理由 |
| executive_summary | TEXT | 执行摘要 |
| detailed_analysis | TEXT | 详细分析 |
| previous_rating | TEXT | 上期评级 |
| rating_change_reason | TEXT | 评级变动原因 |
| changes_from_previous | TEXT | 与上期对比（v3 新增） |
| signal_summary | TEXT (JSON) | 五路信号摘要 SignalSummary（v7 新增） |
| debate_detail | TEXT (JSON) | Bull/Bear 辩论原始结构化数据（v9 新增） |
| technical_detail | TEXT (JSON) | 技术面分析原始结构化数据（v9 新增） |
| financial_detail | TEXT | 财报分析格式化文本（v10 新增） |
| news_detail | TEXT | 新闻分析格式化文本（v10 新增） |
| xueqiu_detail | TEXT | 雪球分析格式化文本（v10 新增） |
| analyst_signals | TEXT (JSON) | 五路标准化信号 AnalystSignals（v11 新增） |

索引: `idx_reports_framework`

#### reflections — 反思记忆（v8 新增）
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| framework_id | INTEGER FK | 关联 frameworks |
| role | TEXT NOT NULL | 角色标识: bull/bear/financial/news/technical/risk_advisor |
| report_id | INTEGER FK | 关联 reports（被反思的报告） |
| situation | TEXT | 当时情况描述 |
| prediction | TEXT | 当时预测/判断 |
| actual_outcome | TEXT | 实际结果（价格涨跌等） |
| was_correct | INTEGER | 预测是否正确（0/1） |
| reflection | TEXT | AI 生成的结构化反思（归因+教训+改进） |
| created_at | TIMESTAMP | 创建时间 |

索引: `idx_reflections_framework_role`

#### chat_sessions — 对话会话（v12 新增）
| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID 字符串 |
| framework_id | INTEGER FK | 关联 frameworks |
| model_provider | TEXT | AI 模型: anthropic / deepseek |
| created_at / updated_at | TIMESTAMP | 时间戳 |

索引: `idx_chat_sessions_framework`

#### chat_messages — 对话消息（v12 新增）
| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| session_id | TEXT FK | 关联 chat_sessions |
| role | TEXT NOT NULL | user / assistant / system |
| content | TEXT NOT NULL | 消息内容 |
| specialist | TEXT | 回答角色: general/financial/quant/sentiment/debate/competitor |
| data_refs | TEXT (JSON) | 引用的数据标识数组 |
| created_at | TIMESTAMP | 创建时间 |

索引: `idx_chat_messages_session`

**表间关系**: `frameworks` 1:N → `news_articles`, `analyses`, `reports`, `reflections`, `chat_sessions`（均通过 framework_id 外键）；`chat_sessions` 1:N → `chat_messages`

### Pydantic 数据模型 (`models.py`)

| 模型 | 用途 | 关键字段 |
|------|------|---------|
| AnalysisFramework | 分析框架 | company_name, stock_code, keywords[], competitors[] |
| NewsArticle | 新闻条目 | framework_id, title, url, url_hash, relevance_score |
| NewsAnalysisItem | 单条新闻分析 | news_id, relevance, category, sentiment, summary |
| WeeklyAnalysis | 周度分析 | week_start/end, news_analyses[], weekly_summary |
| NewsReference | 新闻链接引用 | title, url |
| RiskItem | 风险项 | description, severity(高/中/低), supporting_news[] |
| OpportunityItem | 机会项 | description, confidence(高/中/低), supporting_news[] |
| AnalystSignal | 单路标准化信号 | signal(bullish/bearish/neutral), confidence(0-1 float) |
| AnalystSignals | 五路标准化信号汇总 | news, financial, sentiment, technical, debate（各为 AnalystSignal） |
| SignalSummary | 五路信号摘要 | news_signal, financial_signal, sentiment_signal, technical_signal, debate_lean, consistency, confidence(float), conflicts, overall_signal, overall_confidence |
| InvestmentReport | 投研报告 | investment_rating, signal_summary, analyst_signals, debate_detail, technical_detail, risks[], opportunities[], changes_from_previous |
| Reflection | 反思记忆 | framework_id, role, report_id, situation, prediction, actual_outcome, was_correct, reflection |
| ChatSession | 对话会话 | id(UUID), framework_id, model_provider |
| ChatMessage | 对话消息 | session_id, role, content, specialist, data_refs[] |

嵌套关系: `InvestmentReport` → `SignalSummary` + `RiskItem`/`OpportunityItem` → `NewsReference`

### Repository 层 (`data/`)

所有 Repo 接收 `sqlite3.Connection`，负责 Pydantic 模型 ↔ SQLite 行的序列化/反序列化。

| 类 | 主要方法 |
|---|---|
| FrameworkRepo | `save`, `get_by_id`, `list_all`, `update`, `delete` |
| NewsRepo | `insert_if_not_exists`(URL去重), `get_by_framework`(按日期范围), `exists_by_url_hash` |
| AnalysisRepo | `save`, `get_recent`(最近N周), `get_latest` |
| ReportRepo | `save`, `get_by_id`, `get_latest`, `get_by_framework` |
| ReflectionRepo | `save`, `get_by_framework_and_role`, `get_by_industry_and_role`(跨股票), `exists_for_report` |

JSON 序列化约定: 存入 `json.dumps(model.model_dump())`，读出 `json.loads()` → Pydantic 构造。

### 服务层 (`services/`)

| 服务 | 职责 | 外部依赖 |
|------|------|---------|
| FrameworkService | 通过 Claude AI 自动/交互式构建分析框架 | Claude API |
| CrawlService | 并行抓取 6 个新闻源，去重（URL hash + 标题相似度），熔断机制 | AKShare/NewsAPI/RSS/CLS/DuckDuckGo/Tavily |
| AnalysisService | 增量周度新闻分析，构建历史上下文，JSON 修复 | Claude API |
| FinancialAnalysisService | 财报 AI 深度分析（CoT 思维链） | Claude API |
| XueqiuOpinionService | 雪球帖子 AI 情绪分析 | Claude API + Playwright |
| TechnicalAnalysisService | 技术指标计算（pandas: MA/RSI/MACD/布林带）+ AI 解读 | Claude API |
| DebateService | Bull/Bear 辩论编排: Bull 先论述 → Bear 反驳 | Claude API |
| ReflectionService | 反思记忆: 对比评级 vs 实际涨跌 → 生成教训 → 注入下次分析 | Claude API + StockHistoryService |
| ReportService | 综合五路信号+辩论+记忆生成投研报告 | Claude API |
| ResearchPipeline | 编排完整流程: 反思→抓新闻→五路分析→辩论→生报告，SSE 推送进度 | 组合以上服务 |
| StockQuoteService | 实时行情（雪球 API），NaN/Inf 安全处理 | AKShare（通过 xq_token_manager） |
| StockHistoryService | 历史价格（A/US/HK 分市场），美股交易所前缀缓存 | AKShare（通过 xq_token_manager） |
| FinancialDataService | 财报指标摘要（营收/利润/ROE 等） | AKShare |
| xq_token_manager | 雪球 token 管理: 缓存/过期检测/Playwright 刷新/回退 | AKShare, Playwright |
| xueqiu_analysis | 雪球大V观点: Playwright 绕 WAF + 页面内 fetch 帖子 API | Playwright |
| market_utils | 共享工具: 市场检测、代码标准化、名称搜索（进程级缓存） | AKShare |
| ClaudeClient | Claude API 封装: 重试/退避、JSON 提取、prompt 文件加载 | Anthropic API |
| ChatService | 对话核心: Intent Router + Context Assembler + 流式 AI 调用 | Anthropic/DeepSeek API |
| IntentRouter | 意图分类: 规则优先(关键词匹配) + LLM 兜底 | ClaudeClient（可选） |
| ContextAssembler | 按角色组装本地数据上下文，数据新鲜度检查 | DB Repos |

### 核心数据流

```
用户发起研究 (POST /api/research)
  │
  ├─ 0. ReflectionService.check_and_reflect()
  │     对比上期报告评级 vs 实际价格涨跌 → 为每个角色生成教训 → ReflectionRepo.save()
  │
  ├─ 1. FrameworkService → Claude AI 生成框架 → FrameworkRepo.save()
  │
  ├─ 2. CrawlService → 6源并行抓取 → 去重 → NewsRepo.insert_if_not_exists()
  │     FinancialDataService → AKShare 财报数据（不入库，作为上下文传入）
  │
  ├─ 3. 五路并行分析（各注入历史教训）
  │     3a. FinancialAnalysisService → 财报 AI 深度分析（CoT）
  │     3b. XueqiuOpinionService → 雪球情绪分析
  │     3c. AnalysisService → 新闻 AI 分析（CoT）→ AnalysisRepo.save()
  │     3d. TechnicalAnalysisService → pandas 算指标 + AI 解读（CoT）
  │     3e. DebateService → Bull 论述 → Bear 反驳（注入 bull/bear 历史教训）
  │
  └─ 4. ReportService → 五路信号 + 辩论裁决 + risk_advisor 历史教训
        → Claude AI (risk_advisor.md) → 交叉验证 + 冲突处理 → ReportRepo.save()
```

```
股票查询 (GET /api/stock/quote?code=英伟达)
  │
  ├─ web._resolve_stock_code() → 代码检测 / 框架DB匹配 / AKShare名称搜索
  │
  └─ StockQuoteService.fetch_quote() → xq_token_manager.call_xq_api() → 雪球API → 返回 JSON
       token 过期时自动刷新: KeyError → Playwright 刷新 → 重试 / 回退默认 token
```

### 设计要点

- **JSON in SQLite**: 复杂嵌套结构（risks/opportunities/news_analyses）存为 JSON TEXT，避免过度拆表
- **URL 去重**: news_articles 通过 url_hash (SHA256) UNIQUE 约束 + insert_if_not_exists 实现幂等插入
- **增量分析**: AnalysisService 从上次分析的 week_end 开始，避免重复分析
- **熔断机制**: CrawlService 对连续失败 3 次的新闻源自动跳过
- **进程级缓存**: 股票名称映射、美股交易所前缀首次加载后常驻内存
- **JSON 修复**: Claude 返回的 JSON 可能截断/格式错误，AnalysisService 和 ReportService 均含 repair 逻辑
- **NaN 安全**: 股票行情中 AKShare 返回的 NaN/Inf 统一转为 null，避免 JSON 序列化崩溃
- **雪球 token 自动刷新**: `xq_token_manager` 封装所有雪球 API 调用，token 过期时自动通过 Playwright 刷新，失败则回退 AKShare 默认值
- **Financial CoT**: 所有分析 prompt 要求先列数据→逐步推理→再输出 JSON，`_extract_json` 自动跳过 pre-JSON 推理文本
- **Bull/Bear 辩论**: Bull 先论述 → Bear 接收 Bull 论点逐条反驳，risk_advisor 做最终裁决，减少单向偏见
- **信号一致性矩阵**: risk_advisor.md 定义 7 种五路信号组合（全部看多/看空/基本面vs技术面背离等），每种对应置信度和操作建议
- **反思记忆**: 每次分析前对比上期评级 vs 实际涨跌，LLM 生成结构化反思（归因+教训），持久化到 SQLite，下次分析时注入同股票(3条)+同行业跨股票(2条)教训
- **跨股票迁移学习**: ReflectionRepo.get_by_industry_and_role() 通过 JOIN frameworks 表按行业查询，实现同行业不同股票间的经验共享

## 关键文件

### 表现层
- `src/invest_research/presentation/web.py` — FastAPI 路由（API 端点 + SSE 推送）
- `src/invest_research/static/index.html` — 前端单页面（HTML/CSS/JS 一体）
- `src/invest_research/static/openclaw_plugin.js` — OpenClaw 机器人插件

### 服务层
- `src/invest_research/services/research_pipeline.py` — 研究流程编排（五阶段 + 反思）
- `src/invest_research/services/framework_service.py` — 框架构建（Claude AI）
- `src/invest_research/services/crawl_service.py` — 新闻抓取与去重
- `src/invest_research/services/analysis_service.py` — 周度 AI 新闻分析
- `src/invest_research/services/financial_analysis_service.py` — 财报 AI 深度分析
- `src/invest_research/services/xueqiu_opinion_service.py` — 雪球帖子 AI 情绪分析
- `src/invest_research/services/technical_analysis_service.py` — 技术面分析（pandas 指标 + AI 解读）
- `src/invest_research/services/debate_service.py` — Bull/Bear 辩论编排
- `src/invest_research/services/reflection_service.py` — 反思记忆系统（对比→反思→持久化→注入）
- `src/invest_research/services/report_service.py` — 综合报告生成（五路信号 + 辩论裁决）
- `src/invest_research/services/claude_client.py` — Claude API 客户端
- `src/invest_research/services/market_utils.py` — 市场检测/代码标准化/名称搜索
- `src/invest_research/services/xq_token_manager.py` — 雪球 token 管理（缓存/刷新/回退）
- `src/invest_research/services/xueqiu_analysis.py` — 雪球大V观点抓取（Playwright 绕 WAF）
- `src/invest_research/services/stock_quote_service.py` — 实时报价服务
- `src/invest_research/services/stock_history_service.py` — 历史价格服务
- `src/invest_research/services/financial_service.py` — 财务数据服务

### Prompt 文件（`config/prompts/`）
- `risk_advisor.md` — 综合报告：五路交叉验证 + 辩论裁决 + 信号一致性矩阵
- `news_analyst.md` — 新闻分析（CoT: 扫描→锚定→判断→综合）
- `financial_analyst.md` — 财报分析（CoT: 列数据→找拐点→交叉验证→对标→结论）
- `xueqiu_analyst.md` — 雪球情绪（CoT: 筛选→提炼→对照→找分歧→判断）
- `technical_analyst.md` — 技术面分析（CoT: 列价位→判趋势→识形态→结论）
- `bull_researcher.md` — 看多研究员（构建看多论述 + 承认风险）
- `bear_researcher.md` — 看空研究员（反驳看多方 + 风险因素）
- `reflector.md` — 反思 prompt（结果对比→归因→教训→改进建议）
- `framework_builder.md` / `framework_builder_pro.md` — 框架构建

### 数据层
- `src/invest_research/models.py` — Pydantic 数据模型（含 SignalSummary、Reflection）
- `src/invest_research/data/database.py` — 数据库初始化与迁移（schema v12）
- `src/invest_research/data/framework_repo.py` — 框架 Repository
- `src/invest_research/data/news_repo.py` — 新闻 Repository
- `src/invest_research/data/analysis_repo.py` — 分析 Repository
- `src/invest_research/data/report_repo.py` — 报告 Repository（含 signal_summary 序列化）
- `src/invest_research/data/reflection_repo.py` — 反思记忆 Repository（同股票 + 跨股票查询）
- `src/invest_research/data/chat_repo.py` — 对话 Repository（会话 + 消息 CRUD）

### 对话系统
- `src/invest_research/services/chat_service.py` — 对话核心（两轮架构：Pass 1 数据需求分析 + Pass 2 流式回答）
- `src/invest_research/services/data_fetcher.py` — 按需数据拉取调度器（8 类数据源，结果写入长期记忆）
- `src/invest_research/services/intent_router.py` — 意图路由（规则+LLM兜底）
- `src/invest_research/services/context_assembler.py` — 上下文组装（数据目录+按角色取数据+额外数据合并）
- `src/invest_research/services/context_compressor.py` — 对话历史压缩（LLM 摘要+近期保留）
- `config/prompts/data_needs.md` — Pass 1 数据需求分析 prompt
- `config/prompts/chat_general.md` — 综合顾问对话 prompt
- `config/prompts/chat_financial.md` — 财务分析师对话 prompt
- `config/prompts/chat_quant.md` — 量化分析师对话 prompt
- `config/prompts/chat_sentiment.md` — 情绪分析师对话 prompt
- `config/prompts/chat_debate.md` — 多空辩手对话 prompt
- `config/prompts/chat_competitor.md` — 竞品分析师对话 prompt（占位）

### 测试
- `tests/test_stock_services.py` — 股票服务单元测试（32 个用例）
- `tests/test_xq_token_manager.py` — 雪球 token 管理器测试（6 个用例）

## API 接口文档

服务地址: `http://<服务器IP>:8000`

所有接口均为 GET 请求，返回 JSON。字段值为 `null` 表示无数据，`error` 非空表示查询失败。
股票代码格式：A股 6位数字(`600519`)、港股 5位数字(`00700`)、美股英文字母(`MSFT`)。
`code` 参数支持智能解析：可输入标准代码、短代码（如 `700` → `00700`）或中文公司名称（如 `英伟达` → `NVDA`）。

### 1. 实时股票报价

```
GET /api/stock/quote?code={股票代码}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `code` | 是 | 股票代码或公司名称。代码: `600519`/`MSFT`/`00700`，名称: `贵州茅台`/`英伟达`/`腾讯` |

返回字段: `market`(市场), `code`, `name`(名称), `price`(现价), `change`(涨跌额), `change_pct`(涨跌幅%), `open`(今开), `high`(最高), `low`(最低), `prev_close`(昨收), `volume`(成交量), `amount`(成交额), `pe_ttm`(市盈率), `pb`(市净率), `market_cap`(总市值/元), `dividend_yield`(股息率%), `week52_high`(52周高), `week52_low`(52周低), `currency`(货币), `timestamp`, `error`

返回示例:
```json
{
  "market": "US", "code": "PDD", "name": "拼多多",
  "price": 102.92, "change": 1.09, "change_pct": 1.0704,
  "open": 103.26, "high": 104.2, "low": 102.8, "prev_close": 101.83,
  "volume": 5442931.0, "amount": 562261306.0,
  "pe_ttm": 9.862, "pb": 2.577, "market_cap": 146110013869.0,
  "dividend_yield": null, "week52_high": 139.41, "week52_low": 87.11,
  "currency": "USD", "timestamp": "2026-02-19 05:00:00", "error": ""
}
```

### 2. 历史价格查询

```
GET /api/stock/history?code={代码}&start_date={开始}&end_date={结束}&period={周期}&adjust={复权}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `code` | 是 | 股票代码 |
| `start_date` | 是 | 开始日期，格式 `YYYYMMDD` |
| `end_date` | 是 | 结束日期，格式 `YYYYMMDD` |
| `period` | 否 | `daily`(日线，默认) / `weekly`(周线) / `monthly`(月线) |
| `adjust` | 否 | `qfq`(前复权，默认) / `hfq`(后复权) / 空串(不复权) |

返回字段: `market`, `code`, `period`, `adjust`, `error`, `data`(数组，按日期升序)
每条 data: `date`, `open`, `close`, `high`, `low`, `volume`(成交量), `amount`(成交额), `change_pct`(涨跌幅%), `turnover`(换手率%)

返回示例:
```json
{
  "market": "US", "code": "PDD", "period": "daily", "adjust": "qfq",
  "data": [
    {"date": "2026-01-02", "open": 116.215, "close": 115.75, "high": 116.93, "low": 115.235, "volume": 5688949, "amount": 660712864.0, "change_pct": 2.08, "turnover": 0.4}
  ],
  "error": ""
}
```

### 3. 公司财报研究

```
GET /api/stock/financial?code={股票代码}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `code` | 是 | 股票代码 |

返回字段: `stock_code`, `summary`(格式化纯文本财报摘要，含营收/净利润/毛利率/净利率/ROE/ROA等), `error`

### 4. 调研报告列表

```
GET /api/reports
```

无参数。按公司分组返回所有报告摘要。

返回示例:
```json
[
  {
    "company_name": "拼多多", "industry": "电子商务",
    "sub_industry": "综合电商平台", "framework_id": 1,
    "reports": [
      {"id": 3, "report_date": "2026-02-13", "investment_rating": "推荐", "executive_summary": "总体向好..."}
    ]
  }
]
```

`investment_rating` 取值: `强烈推荐` / `推荐` / `中性` / `谨慎` / `回避`。`id` 用于查询报告详情。

### 5. 调研报告详情

```
GET /api/reports/{report_id}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `report_id` | 是 | 报告ID（路径参数），从报告列表获取 |

返回字段: `id`, `company_name`, `industry`, `report_date`, `investment_rating`, `rating_rationale`(评级理由), `executive_summary`(执行摘要), `detailed_analysis`(详细分析), `previous_rating`(上期评级), `rating_change_reason`(评级变动原因), `changes_from_previous`(与上期对比), `risks`(风险数组), `opportunities`(机会数组)

risks 每项: `description`, `severity`(高/中/低), `probability`, `impact`, `supporting_news`([{title, url}])
opportunities 每项: `description`, `confidence`, `timeframe`, `impact`, `supporting_news`([{title, url}])

### 6. 雪球大V观点

```
GET /api/stock/xueqiu-analysis?code={股票代码}
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `code` | 是 | 股票代码或公司名称 |

返回字段: `stock_code`, `symbol`(雪球格式), `posts`(帖子数组), `error`
每条 post: `user`(用户名), `followers`(粉丝数), `title`(帖子标题/摘要), `url`(帖子链接), `time`(发布时间), `likes`(点赞数), `comments`(评论数)

注意: 首次调用约需 15-20 秒（Playwright 启动 + WAF 挑战），帖子按粉丝数+互动量排序。

### 7. 关注股票列表

```
GET /api/frameworks
```

无参数。返回系统中已关注的所有股票。

返回示例:
```json
[
  {
    "id": 1, "company_name": "拼多多", "stock_code": "PDD",
    "industry": "电子商务", "sub_industry": "综合电商平台",
    "is_active": true, "created_at": "2026-02-13 10:30:00"
  }
]
```

### 8. 最近对话股票

```
GET /api/chat/recent-stocks
```

无参数。返回有对话记录的股票，按最近对话时间排序去重。

返回字段: `framework_id`, `company_name`, `stock_code`, `last_chat_at`, `session_count`

返回示例:
```json
[
  {
    "framework_id": 6, "company_name": "中国长江电力", "stock_code": "600900",
    "last_chat_at": "2026-04-04 03:53:43", "session_count": 1
  }
]
```
