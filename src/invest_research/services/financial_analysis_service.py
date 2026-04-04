import json
import logging

from invest_research.models import AnalysisFramework
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class FinancialAnalysisService:
    """调用 AI 对财报数据进行结构化分析。"""

    def __init__(self, claude_client: ClaudeClient):
        self.claude = claude_client

    def analyze(self, framework: AnalysisFramework, financial_data: str) -> dict:
        """基于框架和财报原始数据，返回结构化财报分析结论。"""
        if not financial_data or "获取失败" in financial_data:
            return self._empty_result("财报数据不可用")

        framework_context = self._build_context(framework)

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 财报数据（连续多期）\n{financial_data}\n\n"
            f"请基于以上财报数据和分析框架，输出结构化的财务分析结论。"
            f"注意输出的 JSON 中所有字符串值内的双引号必须用反斜杠转义。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            prompt_name="financial_analyst",
            model=self.claude.settings.claude_model_heavy,
            max_tokens=4096,
        )

        return self._parse_result(response)

    def format_for_report(self, result: dict) -> str:
        """将结构化分析结果格式化为可读文本，供报告模块使用。"""
        if not result or result.get("summary") == "财报数据不可用":
            return ""

        parts = []

        # 趋势分析
        trend = result.get("trend_analysis", {})
        if trend:
            parts.append("【趋势分析】")
            if trend.get("revenue"):
                parts.append(f"  营收: {trend['revenue']}")
            if trend.get("profitability"):
                parts.append(f"  盈利: {trend['profitability']}")
            if trend.get("growth_quality"):
                parts.append(f"  增长质量: {trend['growth_quality']}")

        # 关键指标
        metrics = result.get("key_metrics_assessment", [])
        if metrics:
            parts.append("【关键指标】")
            for m in metrics:
                parts.append(
                    f"  {m.get('metric', '?')}: {m.get('values', '')} "
                    f"({m.get('trend', '')}) — {m.get('comment', '')}"
                )

        # 预警
        flags = result.get("red_flags", [])
        if flags:
            parts.append(f"【预警信号】{'; '.join(flags)}")

        # 行业适配度
        fitness = result.get("fitness_assessment", "")
        if fitness:
            parts.append(f"【行业适配度】{fitness}")

        # 策略评估
        strategy = result.get("strategy_assessment", "")
        if strategy:
            parts.append(f"【策略评估】{strategy}")

        # 数据缺失
        gaps = result.get("data_gaps", [])
        if gaps:
            parts.append(f"【数据缺失】{', '.join(gaps)}")

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
        if "financial_focus" in dims:
            ff = dims["financial_focus"]
            lines.append(f"关键财务指标: {', '.join(ff.get('key_metrics', []))}")
            lines.append(f"预警信号: {', '.join(ff.get('red_flags', []))}")
        if "strategy_specific" in dims:
            ss = dims["strategy_specific"]
            lines.append("策略关注维度:")
            for k, v in ss.items():
                lines.append(f"  - {k}: {v}")

        return "\n".join(lines)

    @staticmethod
    def _parse_result(response: str) -> dict:
        try:
            json_str = ClaudeClient._extract_json(response)
            return json.loads(json_str)
        except Exception as e:
            logger.warning(f"财报分析 JSON 解析失败: {e}")
            # 回退：返回原始文本作为 summary
            return {
                "trend_analysis": {},
                "key_metrics_assessment": [],
                "red_flags": [],
                "fitness_assessment": "",
                "strategy_assessment": "",
                "data_gaps": [],
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
            "trend_analysis": {},
            "key_metrics_assessment": [],
            "red_flags": [],
            "fitness_assessment": "",
            "strategy_assessment": "",
            "data_gaps": [],
            "signal": "neutral",
            "confidence": 0.0,
            "summary": reason,
        }
