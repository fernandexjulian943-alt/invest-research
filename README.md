# Invest-Research

AI 驱动的投资研究分析系统，提供股票数据查询、AI 投研报告生成、增量新闻抓取等功能。

## 核心功能

### 股票数据查询

支持 A 股、美股、港股三个市场，代码输入支持中文名称智能解析。

| 功能 | API | 说明 |
|------|-----|------|
| 实时报价 | `GET /api/stock/quote?code=茅台` | 现价、涨跌、PE/PB、市值、股息率 |
| 历史K线 | `GET /api/stock/history?code=NVDA&start_date=20210101&end_date=20260301&period=monthly` | 含年化收益率、最大回撤统计 |
| 财报摘要 | `GET /api/stock/financial?code=00700` | 营收、净利润、ROE 等关键指标 |
| 分红查询 | `GET /api/stock/dividend?code=600519` | 历史分红明细、累计分红、年度趋势 |

**智能代码解析**：直接输入中文名即可 —— `茅台`→600519、`英伟达`→NVDA、`腾讯`→00700

**多数据源容错**：东方财富为主，腾讯/新浪为备用，某个源挂了自动切换。

### AI 投研报告

- 自动抓取多源新闻（RSS、NewsAPI、DuckDuckGo、Tavily 等）
- Claude AI 分析新闻，生成投资评级和风险/机会分析
- 增量更新，每周自动生成对比报告

### 关注股票管理

- Web 界面管理关注股票列表
- 一键查看财报摘要
- 支持启停监控

## 部署步骤

### 前置条件

- Python 3.11+
- pip（包管理）

### 安装

```bash
# 1. 克隆代码
git clone https://github.com/lilywang-lx/invest-research-.git
cd invest-research-

# 2. 安装（推荐开发模式，方便调试）
pip install -e .

# 3. 创建配置文件
cp .env.example .env
# 编辑 .env，填入：
#   ANTHROPIC_API_KEY=你的 Claude API Key（投研报告需要）
#   NEWSAPI_API_KEY=（可选，新闻抓取）
#   TAVILY_API_KEY=（可选，搜索增强）
# 注意：仅股票数据查询功能不需要任何 API Key

# 4. 启动服务
invest-research serve --host 0.0.0.0 --port 8001

# 5. 验证
curl http://localhost:8001/api/stock/quote?code=000001
```

### 保持后台运行（systemd）

```bash
cat > /etc/systemd/system/invest-research.service << 'EOF'
[Unit]
Description=Invest Research API Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/invest-research-
ExecStart=/usr/local/bin/invest-research serve --host 0.0.0.0 --port 8001
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl enable --now invest-research
```

### 健康检查（可选）

```bash
# 复制健康检查脚本
cp healthcheck.sh /usr/local/bin/invest-research-healthcheck.sh
chmod +x /usr/local/bin/invest-research-healthcheck.sh

# 添加 cron 每小时检查
echo "0 * * * * /usr/local/bin/invest-research-healthcheck.sh" | crontab -
```

## API 文档

### 实时报价

```
GET /api/stock/quote?code={股票代码或名称}
```

返回：现价、涨跌幅、PE/PB、市值、股息率、52周高低等。

```json
{
  "market": "US", "code": "NVDA", "name": "英伟达",
  "price": 177.19, "change": -7.7, "change_pct": -4.16,
  "pe_ttm": 38.5, "market_cap": 4300000000000,
  "error": ""
}
```

### 历史K线

```
GET /api/stock/history?code={代码}&start_date={YYYYMMDD}&end_date={YYYYMMDD}&period={daily|weekly|monthly}&adjust={qfq|hfq}
```

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| code | 是 | - | 股票代码或中文名 |
| start_date | 是 | - | 开始日期 YYYYMMDD |
| end_date | 是 | - | 结束日期 YYYYMMDD |
| period | 否 | daily | daily/weekly/monthly |
| adjust | 否 | qfq | qfq(前复权)/hfq(后复权)/空(不复权) |

返回包含 `stats` 统计：总收益率、年化收益率、最大回撤、交易日数。

### 财报摘要

```
GET /api/stock/financial?code={代码}
```

返回格式化的财报摘要文本（营收、净利润、毛利率、净利率、ROE 等）。

### 分红查询

```
GET /api/stock/dividend?code={代码}
```

返回：历史分红明细、累计分红统计、年度趋势。A 股/港股返回完整记录，美股返回当前股息率。

### 投研报告

```
GET /api/reports              # 报告列表（按公司分组）
GET /api/reports/{id}         # 报告详情
GET /api/frameworks           # 关注股票列表
POST /api/research            # 触发研究任务
GET /api/research/{id}/events # 研究进度（SSE）
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 数据库 | SQLite（WAL 模式） |
| 股票数据 | AKShare（东方财富/腾讯/新浪多源） |
| AI 分析 | Claude API |
| 新闻抓取 | NewsAPI / RSS / DuckDuckGo / Tavily |
| Token 管理 | Playwright（雪球 token 自动刷新） |

## 目录结构

```
invest-research/
├── src/invest_research/
│   ├── main.py                    # CLI 入口
│   ├── config.py                  # 配置
│   ├── models.py                  # Pydantic 数据模型
│   ├── presentation/
│   │   ├── web.py                 # FastAPI 路由
│   │   └── markdown_renderer.py   # 报告渲染
│   ├── services/
│   │   ├── stock_quote_service.py    # 实时报价
│   │   ├── stock_history_service.py  # 历史K线 + 统计
│   │   ├── financial_service.py      # 财报摘要
│   │   ├── dividend_service.py       # 分红查询
│   │   ├── market_utils.py           # 市场检测/代码解析
│   │   ├── xq_token_manager.py       # 雪球token管理
│   │   ├── akshare_utils.py          # AKShare调用包装
│   │   ├── research_pipeline.py      # 研究流程编排
│   │   ├── framework_service.py      # 框架构建
│   │   ├── crawl_service.py          # 新闻抓取
│   │   ├── analysis_service.py       # AI分析
│   │   ├── report_service.py         # 报告生成
│   │   └── claude_client.py          # Claude API客户端
│   ├── data/                      # Repository 层
│   ├── static/                    # 前端页面
│   └── crawlers/                  # 爬虫模块
├── config/prompts/                # AI Prompt 模板
├── healthcheck.sh                 # 健康检查脚本
├── .env.example                   # 环境变量示例
└── pyproject.toml                 # 项目配置
```

## 注意事项

- 股票数据查询功能**不需要任何 API Key**，开箱即用
- 投研报告生成需要 `ANTHROPIC_API_KEY`
- 东方财富 API 可能限流封 IP，系统会自动切换腾讯/新浪备用源
- 雪球 token 自动刷新需要 Playwright（`playwright install chromium`）
- 数据库文件在 `data/invest_research.db`，已在 .gitignore 中排除
