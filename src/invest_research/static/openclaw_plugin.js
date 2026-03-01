// OpenClaw 插件 — AI 投研分析系统工具集
//
// 使用前请将 API_BASE 改为你的实际服务地址。
// 注册了 5 个工具：
//   1. stock_quote       — 实时股票报价
//   2. stock_history     — 历史价格查询
//   3. stock_financial   — 公司财报研究
//   4. research_reports  — 调研报告查询
//   5. tracked_stocks    — 关注股票列表

const API_BASE = "http://localhost:8001";

async function callAPI(path) {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`API ${resp.status}: ${body}`);
  }
  return resp.json();
}

// ---------- 格式化辅助 ----------

function fmtNumber(n) {
  if (n === null || n === undefined) return "-";
  const abs = Math.abs(n);
  if (abs >= 1e12) return (n / 1e12).toFixed(2) + " 万亿";
  if (abs >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
  if (abs >= 1e4) return (n / 1e4).toFixed(2) + " 万";
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function fmtQuote(d) {
  if (d.error) return `查询失败: ${d.error}`;
  const sign = (d.change ?? 0) >= 0 ? "+" : "";
  const lines = [
    `${d.name} (${d.code}) | ${d.market}股`,
    `现价: ${d.price} ${d.currency}  ${sign}${d.change ?? "-"} (${sign}${d.change_pct != null ? d.change_pct.toFixed(2) + "%" : "-"})`,
    "",
    `今开: ${d.open ?? "-"}  昨收: ${d.prev_close ?? "-"}`,
    `最高: ${d.high ?? "-"}  最低: ${d.low ?? "-"}`,
    `成交量: ${fmtNumber(d.volume)}  成交额: ${fmtNumber(d.amount)}`,
    "",
    `市盈率(TTM): ${d.pe_ttm ?? "-"}  市净率: ${d.pb ?? "-"}`,
    `总市值: ${fmtNumber(d.market_cap)}  股息率: ${d.dividend_yield != null ? d.dividend_yield.toFixed(2) + "%" : "-"}`,
    `52周高: ${d.week52_high ?? "-"}  52周低: ${d.week52_low ?? "-"}`,
  ];
  return lines.join("\n");
}

function fmtHistory(d) {
  if (d.error) return `查询失败: ${d.error}`;
  if (!d.data || !d.data.length) return "未查询到历史数据";

  const periodLabel = { daily: "日线", weekly: "周线", monthly: "月线" };
  const header = `${d.code} ${d.market}股 ${periodLabel[d.period] || d.period} | 共 ${d.data.length} 条`;

  const rows = d.data.slice(-20).reverse();
  const table = rows.map((r) => {
    const pct = r.change_pct != null ? r.change_pct.toFixed(2) + "%" : "-";
    return `${r.date}  开${r.open}  收${r.close}  高${r.high}  低${r.low}  量${fmtNumber(r.volume)}  涨跌${pct}`;
  });

  const note = d.data.length > 20 ? `\n(仅显示最近 20 条，共 ${d.data.length} 条)` : "";
  return [header, "", ...table, note].join("\n");
}

function fmtReport(r) {
  const lines = [
    `# ${r.company_name} 投资研究报告`,
    `日期: ${r.report_date?.split("T")[0] || "-"}  行业: ${r.industry || "-"}`,
    `评级: ${r.investment_rating}`,
    r.previous_rating ? `上期评级: ${r.previous_rating}` : null,
    r.rating_change_reason ? `评级变动: ${r.rating_change_reason}` : null,
    "",
    `## 评级理由`,
    r.rating_rationale,
    "",
    `## 执行摘要`,
    r.executive_summary,
  ];

  if (r.risks?.length) {
    lines.push("", "## 风险评估");
    r.risks.forEach((risk, i) => {
      lines.push(`${i + 1}. [${risk.severity}/${risk.probability}] ${risk.description} — 影响: ${risk.impact}`);
    });
  }
  if (r.opportunities?.length) {
    lines.push("", "## 机会识别");
    r.opportunities.forEach((o, i) => {
      lines.push(`${i + 1}. [置信${o.confidence}/${o.timeframe}] ${o.description} — 影响: ${o.impact}`);
    });
  }
  if (r.detailed_analysis) {
    lines.push("", "## 详细分析", r.detailed_analysis);
  }
  if (r.changes_from_previous) {
    lines.push("", "## 与上期对比", r.changes_from_previous);
  }
  return lines.filter((l) => l !== null).join("\n");
}

// ---------- 工具注册 ----------

export default function (api) {

  // 1. 实时股票报价
  api.registerTool({
    name: "stock_quote",
    description:
      "获取股票实时行情报价，包括价格、涨跌幅、市盈率、市净率、总市值、成交量等。支持 A股(如 600519)、美股(如 MSFT)、港股(如 00700)。",
    parameters: {
      type: "object",
      properties: {
        code: {
          type: "string",
          description: "股票代码，如 600519(贵州茅台)、MSFT(微软)、00700(腾讯)",
        },
      },
      required: ["code"],
    },
    async execute(_id, params) {
      const data = await callAPI(`/api/stock/quote?code=${encodeURIComponent(params.code)}`);
      return { content: [{ type: "text", text: fmtQuote(data) }] };
    },
  });

  // 2. 历史价格查询
  api.registerTool({
    name: "stock_history",
    description:
      "查询股票历史K线价格数据，可指定日期范围和周期(日/周/月线)。支持 A股、美股、港股。默认查询最近 3 个月日线。",
    parameters: {
      type: "object",
      properties: {
        code: {
          type: "string",
          description: "股票代码，如 600519、MSFT、00700",
        },
        start_date: {
          type: "string",
          description: "开始日期，格式 YYYYMMDD，如 20260101。不传则默认 3 个月前",
        },
        end_date: {
          type: "string",
          description: "结束日期，格式 YYYYMMDD，如 20260219。不传则默认今天",
        },
        period: {
          type: "string",
          enum: ["daily", "weekly", "monthly"],
          description: "K线周期: daily(日线)、weekly(周线)、monthly(月线)，默认 daily",
        },
      },
      required: ["code"],
    },
    async execute(_id, params) {
      const today = new Date();
      const threeMonthsAgo = new Date(today);
      threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 3);

      const fmt = (d) =>
        d.getFullYear().toString() +
        String(d.getMonth() + 1).padStart(2, "0") +
        String(d.getDate()).padStart(2, "0");

      const startDate = params.start_date || fmt(threeMonthsAgo);
      const endDate = params.end_date || fmt(today);
      const period = params.period || "daily";

      const qs = new URLSearchParams({
        code: params.code,
        start_date: startDate,
        end_date: endDate,
        period,
        adjust: "qfq",
      });
      const data = await callAPI(`/api/stock/history?${qs}`);
      return { content: [{ type: "text", text: fmtHistory(data) }] };
    },
  });

  // 3. 公司财报研究
  api.registerTool({
    name: "stock_financial",
    description:
      "获取公司财务报表关键指标摘要，包括营收、净利润、毛利率、净利率、ROE、ROA、资产负债率等。支持 A股、美股、港股。",
    parameters: {
      type: "object",
      properties: {
        code: {
          type: "string",
          description: "股票代码，如 600519、PDD、00700",
        },
      },
      required: ["code"],
    },
    async execute(_id, params) {
      const data = await callAPI(`/api/stock/financial?code=${encodeURIComponent(params.code)}`);
      if (data.error) {
        return { content: [{ type: "text", text: `查询失败: ${data.error}` }] };
      }
      return { content: [{ type: "text", text: data.summary }] };
    },
  });

  // 4. 调研报告查询
  api.registerTool({
    name: "research_reports",
    description:
      "查询 AI 投研系统生成的投资研究报告。不传参数返回所有公司的报告列表；传 report_id 返回某份报告完整内容（含评级、风险、机会、详细分析）。",
    parameters: {
      type: "object",
      properties: {
        report_id: {
          type: "number",
          description: "报告 ID，获取某份报告的完整内容。不传则返回所有报告列表",
        },
      },
      required: [],
    },
    async execute(_id, params) {
      if (params.report_id) {
        const report = await callAPI(`/api/reports/${params.report_id}`);
        return { content: [{ type: "text", text: fmtReport(report) }] };
      }

      const companies = await callAPI("/api/reports");
      if (!companies.length) {
        return { content: [{ type: "text", text: "暂无调研报告" }] };
      }

      const lines = ["# 调研报告列表", ""];
      companies.forEach((c) => {
        lines.push(`## ${c.company_name} (${c.industry || "-"})`);
        c.reports.forEach((r) => {
          const date = r.report_date?.split("T")[0] || "-";
          lines.push(`  - [ID:${r.id}] ${date} | 评级: ${r.investment_rating || "-"}`);
        });
        lines.push("");
      });
      lines.push('提示: 使用 report_id 参数可查看某份报告的完整内容。');
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  });

  // 5. 关注股票列表
  api.registerTool({
    name: "tracked_stocks",
    description:
      "查询系统中已关注的股票列表，显示公司名称、股票代码、行业、状态等信息。",
    parameters: {
      type: "object",
      properties: {},
      required: [],
    },
    async execute(_id, _params) {
      const frameworks = await callAPI("/api/frameworks");
      if (!frameworks.length) {
        return { content: [{ type: "text", text: "暂无关注股票" }] };
      }

      const lines = ["# 关注股票列表", ""];
      frameworks.forEach((fw) => {
        const status = fw.is_active ? "活跃" : "停用";
        lines.push(`- ${fw.company_name} | 代码: ${fw.stock_code || "-"} | 行业: ${fw.industry || "-"} | 状态: ${status}`);
      });
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  });
}
