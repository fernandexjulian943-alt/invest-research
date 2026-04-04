import json
import logging

from invest_research.models import AnalysisFramework
from invest_research.services.claude_client import ClaudeClient
from invest_research.services.market_utils import normalize_stock_code
from invest_research.services.xueqiu_analysis import fetch_xueqiu_posts

logger = logging.getLogger(__name__)


class XueqiuOpinionService:
    """调用雪球抓取 + AI 分析，输出结构化市场情绪结论。"""

    def __init__(self, claude_client: ClaudeClient):
        self.claude = claude_client

    def analyze(self, framework: AnalysisFramework, post_limit: int = 15) -> dict:
        """抓取雪球帖子并进行 AI 分析。"""
        stock_code = normalize_stock_code(framework.stock_code)
        if not stock_code:
            return self._empty_result("无股票代码")

        # 抓取帖子
        xq_data = fetch_xueqiu_posts(stock_code, limit=post_limit)
        if xq_data.get("error"):
            return self._empty_result(f"雪球数据获取失败: {xq_data['error']}")

        posts = xq_data.get("posts", [])
        if not posts:
            return self._empty_result("未获取到雪球讨论帖子")

        # 构建上下文
        framework_context = self._build_context(framework)
        posts_text = self._format_posts(posts)

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 雪球讨论帖子（{len(posts)} 条，按粉丝量+互动量排序）\n{posts_text}\n\n"
            f"请基于以上帖子和分析框架，输出结构化的市场情绪分析。"
            f"注意输出的 JSON 中所有字符串值内的双引号必须用反斜杠转义。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            prompt_name="xueqiu_analyst",
            model=self.claude.settings.claude_model_light,
            max_tokens=4096,
        )

        return self._parse_result(response)

    def format_for_report(self, result: dict) -> str:
        """将结构化分析结果格式化为可读文本，供报告模块使用。"""
        if not result or "获取失败" in result.get("summary", "") or "无股票代码" in result.get("summary", ""):
            return ""

        parts = []

        # 情绪分布
        dist = result.get("sentiment_distribution", {})
        if dist:
            parts.append(
                f"【情绪分布】看多:{dist.get('bullish', 0)} "
                f"看空:{dist.get('bearish', 0)} "
                f"中性:{dist.get('neutral', 0)}"
            )

        # 核心观点
        viewpoints = result.get("key_viewpoints", [])
        if viewpoints:
            parts.append("【核心观点】")
            for v in viewpoints[:5]:
                parts.append(
                    f"  [{v.get('stance', '?')}] {v.get('core_argument', '')} "
                    f"— {v.get('author', '?')}(粉丝{v.get('followers', 0)}, "
                    f"可信度:{v.get('credibility', '?')})"
                )

        # 共识与分歧
        consensus = result.get("consensus", "")
        if consensus:
            parts.append(f"【市场共识】{consensus}")

        divergence = result.get("divergence", "")
        if divergence:
            parts.append(f"【核心分歧】{divergence}")

        # 情绪信号
        signal = result.get("sentiment_signal", "")
        if signal:
            parts.append(f"【情绪信号】{signal}")

        # 总结
        summary = result.get("summary", "")
        if summary:
            parts.append(f"【总结】{summary}")

        # 标准化信号
        signal = result.get("signal", "neutral")
        confidence = result.get("confidence", 0.0)
        parts.append(f"【信号】signal: {signal}, confidence: {confidence}")

        return "\n".join(parts)

    @staticmethod
    def _build_context(framework: AnalysisFramework) -> str:
        lines = [
            f"目标公司: {framework.company_name}",
            f"行业: {framework.industry} - {framework.sub_industry}",
            f"公司类型: {framework.company_type or 'general'}",
        ]
        if framework.investment_strategy and framework.investment_strategy != "balanced":
            strategy_labels = {"high_dividend": "高分红稳定型", "high_growth": "高增长爆发型"}
            lines.append(f"投资策略: {strategy_labels.get(framework.investment_strategy, framework.investment_strategy)}")

        dims = framework.analysis_dimensions or {}
        if "business_model" in dims:
            bm = dims["business_model"]
            kq = bm.get("key_questions", [])
            if kq:
                lines.append(f"核心问题: {'; '.join(kq)}")
        if "valuation_anchor" in dims:
            va = dims["valuation_anchor"]
            lines.append(f"估值方法: {va.get('primary_method', '')}")
            lines.append(f"历史估值: {va.get('historical_range', '')}")
        if "risk_matrix" in dims:
            rm = dims["risk_matrix"]
            all_risks = []
            for cat in ("operational", "financial", "market", "regulatory"):
                all_risks.extend(rm.get(cat, []))
            if all_risks:
                lines.append(f"已识别风险: {', '.join(all_risks[:6])}")

        return "\n".join(lines)

    @staticmethod
    def _format_posts(posts: list[dict]) -> str:
        lines = []
        for i, p in enumerate(posts):
            lines.append(
                f"[{i + 1}] 用户: {p['user']} | 粉丝: {p['followers']} | "
                f"赞: {p['likes']} 评: {p['comments']} | 时间: {p['time']}\n"
                f"    内容: {p['title']}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_result(response: str) -> dict:
        try:
            json_str = ClaudeClient._extract_json(response)
            return json.loads(json_str)
        except Exception as e:
            logger.warning(f"雪球分析 JSON 解析失败: {e}")
            return {
                "sentiment_distribution": {"bullish": 0, "bearish": 0, "neutral": 0},
                "key_viewpoints": [],
                "consensus": "",
                "divergence": "",
                "sentiment_signal": "",
                "signal": "neutral",
                "confidence": 0.0,
                "summary": response.strip()[:500],
            }

    @staticmethod
    def _extract_signal(result: dict) -> tuple[str, float]:
        """从分析结果中提取标准化信号。"""
        signal = result.get("signal", "neutral")
        confidence = result.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.0
        if signal not in ("bullish", "bearish", "neutral"):
            signal = "neutral"
        return signal, min(max(confidence, 0.0), 1.0)

    @staticmethod
    def _empty_result(reason: str) -> dict:
        return {
            "sentiment_distribution": {"bullish": 0, "bearish": 0, "neutral": 0},
            "key_viewpoints": [],
            "consensus": "",
            "divergence": "",
            "sentiment_signal": "",
            "signal": "neutral",
            "confidence": 0.0,
            "summary": reason,
        }
