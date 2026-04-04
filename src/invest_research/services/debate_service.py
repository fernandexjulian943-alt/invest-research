import json
import logging

from invest_research.models import AnalysisFramework
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class DebateService:
    """Bull/Bear 辩论服务：先看多后看空（含反驳），输出双方论述。"""

    def __init__(self, claude_client: ClaudeClient):
        self.claude = claude_client

    def debate(
        self,
        framework: AnalysisFramework,
        financial_context: str,
        xueqiu_context: str,
        news_summary: str,
        technical_context: str,
        bull_memory: str = "",
        bear_memory: str = "",
    ) -> dict:
        """执行一轮辩论：Bull 先论述 → Bear 反驳。"""
        context_block = self._build_context_block(
            framework, financial_context, xueqiu_context, news_summary, technical_context
        )

        # Step 1: Bull 论述
        logger.info("Bull 研究员开始论述...")
        bull_result = self._run_bull(framework, context_block, bull_memory)

        # Step 2: Bear 反驳（注入 Bull 论述）
        logger.info("Bear 研究员开始反驳...")
        bear_result = self._run_bear(framework, context_block, bull_result, bear_memory)

        # 从双方论述力度推断信号（简单启发式，最终裁决由 risk_advisor 做）
        signal, confidence = self._infer_signal(bull_result, bear_result)
        return {"bull": bull_result, "bear": bear_result, "signal": signal, "confidence": confidence}

    def format_for_report(self, result: dict) -> str:
        """格式化为报告文本。"""
        bull = result.get("bull", {})
        bear = result.get("bear", {})

        if not bull.get("thesis") and not bear.get("thesis"):
            return ""

        signal = result.get("signal", "neutral")
        confidence = result.get("confidence", 0.0)

        parts = []

        # Bull 方
        parts.append("=== 看多方论述 ===")
        parts.append(f"核心论点: {bull.get('thesis', '无')}")
        evidence = bull.get("supporting_evidence", [])
        if evidence:
            parts.append("支撑论据:")
            for e in evidence:
                parts.append(f"  - [{e.get('source', '')}] {e.get('point', '')}")
        catalysts = bull.get("catalysts", [])
        if catalysts:
            parts.append(f"催化剂: {'; '.join(catalysts)}")
        risk_ack = bull.get("risk_acknowledgment", "")
        if risk_ack:
            parts.append(f"承认的风险: {risk_ack}")
        target = bull.get("target_scenario", "")
        if target:
            parts.append(f"乐观情景: {target}")

        parts.append("")

        # Bear 方
        parts.append("=== 看空方论述 ===")
        parts.append(f"核心论点: {bear.get('thesis', '无')}")
        counters = bear.get("counter_arguments", [])
        if counters:
            parts.append("反驳看多方:")
            for c in counters:
                parts.append(f"  - 看多方说: {c.get('bull_claim', '')}")
                parts.append(f"    反驳: {c.get('rebuttal', '')}")
        risks = bear.get("risk_factors", [])
        if risks:
            parts.append("风险因素:")
            for r in risks:
                parts.append(f"  - [{r.get('source', '')}] {r.get('risk', '')}")
        worst = bear.get("worst_case", "")
        if worst:
            parts.append(f"悲观情景: {worst}")

        parts.append(f"\n【信号】signal: {signal}, confidence: {confidence}")

        return "\n".join(parts)

    def _run_bull(self, framework: AnalysisFramework, context_block: str, memory: str = "") -> dict:
        memory_section = f"\n\n## 历史教训\n{memory}" if memory else ""
        user_message = (
            f"{context_block}{memory_section}\n\n"
            f"请基于以上四路分析结论，构建看多论述。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            prompt_name="bull_researcher",
            model=self.claude.settings.claude_model_heavy,
            max_tokens=4096,
        )

        return self._parse_result(response, "bull")

    def _run_bear(self, framework: AnalysisFramework, context_block: str, bull_result: dict, memory: str = "") -> dict:
        bull_summary = self._format_bull_for_bear(bull_result)
        memory_section = f"\n\n## 历史教训\n{memory}" if memory else ""

        user_message = (
            f"{context_block}\n\n"
            f"## 看多方论述（你需要反驳）\n{bull_summary}{memory_section}\n\n"
            f"请基于以上四路分析结论和看多方的论述，构建看空论述并逐条反驳看多方。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            prompt_name="bear_researcher",
            model=self.claude.settings.claude_model_heavy,
            max_tokens=4096,
        )

        return self._parse_result(response, "bear")

    @staticmethod
    def _infer_signal(bull_result: dict, bear_result: dict) -> tuple[str, float]:
        """从 bull/bear 论述力度做简单启发式推断。"""
        bull_evidence = len(bull_result.get("supporting_evidence", []))
        bull_catalysts = len(bull_result.get("catalysts", []))
        bear_counters = len(bear_result.get("counter_arguments", []))
        bear_risks = len(bear_result.get("risk_factors", []))

        bull_strength = bull_evidence + bull_catalysts
        bear_strength = bear_counters + bear_risks

        total = bull_strength + bear_strength
        if total == 0:
            return "neutral", 0.3

        # 简单比例判断
        bull_ratio = bull_strength / total
        if bull_ratio > 0.6:
            return "bullish", 0.4 + 0.2 * (bull_ratio - 0.6) / 0.4  # 0.4~0.6
        elif bull_ratio < 0.4:
            return "bearish", 0.4 + 0.2 * (0.4 - bull_ratio) / 0.4
        else:
            return "neutral", 0.3

    @staticmethod
    def _build_context_block(
        framework: AnalysisFramework,
        financial_context: str,
        xueqiu_context: str,
        news_summary: str,
        technical_context: str,
    ) -> str:
        parts = [
            f"## 目标公司\n{framework.company_name} ({framework.stock_code})，{framework.industry}",
        ]
        if framework.investment_strategy and framework.investment_strategy != "balanced":
            strategy_labels = {"high_dividend": "高分红稳定型", "high_growth": "高增长爆发型"}
            parts.append(f"投资策略: {strategy_labels.get(framework.investment_strategy, framework.investment_strategy)}")

        if financial_context:
            parts.append(f"\n## 财报分析结论\n{financial_context}")
        if news_summary:
            parts.append(f"\n## 新闻分析结论\n{news_summary}")
        if xueqiu_context:
            parts.append(f"\n## 雪球市场情绪\n{xueqiu_context}")
        if technical_context:
            parts.append(f"\n## 技术面分析\n{technical_context}")

        return "\n".join(parts)

    @staticmethod
    def _format_bull_for_bear(bull_result: dict) -> str:
        lines = [f"核心论点: {bull_result.get('thesis', '无')}"]
        for e in bull_result.get("supporting_evidence", []):
            lines.append(f"- [{e.get('source', '')}] {e.get('point', '')}")
        catalysts = bull_result.get("catalysts", [])
        if catalysts:
            lines.append(f"催化剂: {'; '.join(catalysts)}")
        risk_ack = bull_result.get("risk_acknowledgment", "")
        if risk_ack:
            lines.append(f"承认的风险: {risk_ack}")
        return "\n".join(lines)

    @staticmethod
    def _parse_result(response: str, role: str) -> dict:
        try:
            json_str = ClaudeClient._extract_json(response)
            return json.loads(json_str)
        except Exception as e:
            logger.warning(f"{role} 辩论 JSON 解析失败: {e}")
            if role == "bull":
                return {"thesis": response.strip()[:300], "supporting_evidence": [], "catalysts": [], "risk_acknowledgment": "", "target_scenario": ""}
            else:
                return {"thesis": response.strip()[:300], "counter_arguments": [], "risk_factors": [], "worst_case": ""}
