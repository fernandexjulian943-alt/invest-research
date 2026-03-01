# 项目进度

## 已完成

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

## 待做

### 关注股票管理功能拓展
- 财报分析内容展示优化（待讨论）

## 数据架构

### 整体分层

```
表现层 (presentation/)     ← FastAPI 路由 + 前端页面
    ↓
服务层 (services/)         ← 业务逻辑、外部API调用（Claude AI、AKShare）
    ↓
数据访问层 (data/)         ← Repository 模式，SQLite 读写
    ↓
数据库 (SQLite, WAL 模式)  ← schema_version=3，4 张业务表
```

依赖方向单向：表现层 → 服务层 → 数据访问层。服务层不直接操作 SQL，数据层不包含业务逻辑。

### 数据库表结构（SQLite, schema v3）

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

索引: `idx_reports_framework`

**表间关系**: `frameworks` 1:N → `news_articles`, `analyses`, `reports`（均通过 framework_id 外键）

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
| InvestmentReport | 投研报告 | investment_rating, risks[], opportunities[], changes_from_previous |

嵌套关系: `InvestmentReport` → `RiskItem`/`OpportunityItem` → `NewsReference`

### Repository 层 (`data/`)

所有 Repo 接收 `sqlite3.Connection`，负责 Pydantic 模型 ↔ SQLite 行的序列化/反序列化。

| 类 | 主要方法 |
|---|---|
| FrameworkRepo | `save`, `get_by_id`, `list_all`, `update`, `delete` |
| NewsRepo | `insert_if_not_exists`(URL去重), `get_by_framework`(按日期范围), `exists_by_url_hash` |
| AnalysisRepo | `save`, `get_recent`(最近N周), `get_latest` |
| ReportRepo | `save`, `get_by_id`, `get_latest`, `get_by_framework` |

JSON 序列化约定: 存入 `json.dumps(model.model_dump())`，读出 `json.loads()` → Pydantic 构造。

### 服务层 (`services/`)

| 服务 | 职责 | 外部依赖 |
|------|------|---------|
| FrameworkService | 通过 Claude AI 自动/交互式构建分析框架 | Claude API |
| CrawlService | 并行抓取 6 个新闻源，去重（URL hash + 标题相似度），熔断机制 | AKShare/NewsAPI/RSS/CLS/DuckDuckGo/Tavily |
| AnalysisService | 增量周度新闻分析，构建历史上下文，JSON 修复 | Claude API |
| ReportService | 综合框架+分析+新闻+上期报告生成投研报告 | Claude API |
| ResearchPipeline | 编排完整流程: 建框架→抓新闻→周分析→生报告，SSE 推送进度 | 组合以上服务 |
| StockQuoteService | 实时行情（雪球 API），NaN/Inf 安全处理 | AKShare（通过 xq_token_manager） |
| StockHistoryService | 历史价格（A/US/HK 分市场），美股交易所前缀缓存 | AKShare（通过 xq_token_manager） |
| FinancialDataService | 财报指标摘要（营收/利润/ROE 等） | AKShare |
| xq_token_manager | 雪球 token 管理: 缓存/过期检测/Playwright 刷新/回退 | AKShare, Playwright |
| market_utils | 共享工具: 市场检测、代码标准化、名称搜索（进程级缓存） | AKShare |
| ClaudeClient | Claude API 封装: 重试/退避、JSON 提取、prompt 文件加载 | Anthropic API |

### 核心数据流

```
用户发起研究 (POST /api/research)
  │
  ├─ 1. FrameworkService → Claude AI 生成框架 → FrameworkRepo.save()
  │
  ├─ 2. CrawlService → 6源并行抓取 → 去重 → NewsRepo.insert_if_not_exists()
  │     FinancialDataService → AKShare 财报数据（不入库，作为上下文传入）
  │
  ├─ 3. AnalysisService → 取本周新闻 + 历史分析 → Claude AI → AnalysisRepo.save()
  │
  └─ 4. ReportService → 取分析+新闻+上期报告 → Claude AI → ReportRepo.save()
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

## 关键文件

### 表现层
- `src/invest_research/presentation/web.py` — FastAPI 路由（API 端点 + SSE 推送）
- `src/invest_research/static/index.html` — 前端单页面（HTML/CSS/JS 一体）
- `src/invest_research/static/openclaw_plugin.js` — OpenClaw 机器人插件

### 服务层
- `src/invest_research/services/market_utils.py` — 市场检测/代码标准化/名称搜索
- `src/invest_research/services/xq_token_manager.py` — 雪球 token 管理（缓存/刷新/回退）
- `src/invest_research/services/stock_quote_service.py` — 实时报价服务
- `src/invest_research/services/stock_history_service.py` — 历史价格服务
- `src/invest_research/services/financial_service.py` — 财务数据服务
- `src/invest_research/services/research_pipeline.py` — 研究流程编排
- `src/invest_research/services/framework_service.py` — 框架构建（Claude AI）
- `src/invest_research/services/crawl_service.py` — 新闻抓取与去重
- `src/invest_research/services/analysis_service.py` — 周度 AI 分析
- `src/invest_research/services/report_service.py` — 投研报告生成
- `src/invest_research/services/claude_client.py` — Claude API 客户端

### 数据层
- `src/invest_research/models.py` — Pydantic 数据模型
- `src/invest_research/data/database.py` — 数据库初始化与迁移（schema v3）
- `src/invest_research/data/framework_repo.py` — 框架 Repository
- `src/invest_research/data/news_repo.py` — 新闻 Repository
- `src/invest_research/data/analysis_repo.py` — 分析 Repository
- `src/invest_research/data/report_repo.py` — 报告 Repository

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

### 6. 关注股票列表

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
