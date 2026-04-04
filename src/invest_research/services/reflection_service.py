import json
import logging
from datetime import datetime, timedelta

from invest_research.data.reflection_repo import ReflectionRepo
from invest_research.data.report_repo import ReportRepo
from invest_research.models import AnalysisFramework, InvestmentReport, Reflection
from invest_research.services.claude_client import ClaudeClient
from invest_research.services.stock_history_service import StockHistoryService

logger = logging.getLogger(__name__)

# 评级 → 预期方向映射
RATING_DIRECTION = {
    "强烈推荐": "大幅上涨",
    "推荐": "上涨",
    "中性": "持平",
    "谨慎": "下跌",
    "回避": "大幅下跌",
}

# 角色列表
ROLES = ["bull", "bear", "financial", "news", "technical", "risk_advisor"]


class ReflectionService:
    """反思记忆服务：对比上期预测与实际结果，生成反思并持久化。"""

    def __init__(
        self,
        claude_client: ClaudeClient,
        reflection_repo: ReflectionRepo,
        report_repo: ReportRepo,
    ):
        self.claude = claude_client
        self.reflection_repo = reflection_repo
        self.report_repo = report_repo

    def check_and_reflect(self, framework: AnalysisFramework) -> None:
        """检查上期报告是否需要反思，如需要则触发。"""
        previous_report = self.report_repo.get_latest(framework.id)
        if not previous_report:
            logger.info(f"[{framework.company_name}] 无上期报告，跳过反思")
            return

        # 已经反思过则跳过
        if self.reflection_repo.exists_for_report(previous_report.id):
            logger.info(f"[{framework.company_name}] 报告 {previous_report.id} 已反思过，跳过")
            return

        # 获取从上期报告到现在的股价变化
        actual_outcome = self._get_price_change(
            framework.stock_code, previous_report.report_date
        )
        if not actual_outcome:
            logger.warning(f"[{framework.company_name}] 无法获取股价变化，跳过反思")
            return

        logger.info(
            f"[{framework.company_name}] 开始反思报告 {previous_report.id}："
            f"评级={previous_report.investment_rating}, 实际={actual_outcome}"
        )

        self._reflect_all_roles(framework, previous_report, actual_outcome)

    def get_memories_for_role(
        self, framework: AnalysisFramework, role: str
    ) -> str:
        """获取某角色的历史教训，格式化为可注入 prompt 的文本。"""
        # 同一只股票的反思
        own_memories = self.reflection_repo.get_by_framework_and_role(
            framework.id, role, limit=3
        )
        # 同行业跨股票的反思
        cross_memories = self.reflection_repo.get_by_industry_and_role(
            framework.industry, role, limit=2
        )

        # 去重（同一只股票的可能重复）
        seen_ids = {m.id for m in own_memories}
        all_memories = own_memories + [m for m in cross_memories if m.id not in seen_ids]

        if not all_memories:
            return ""

        lines = ["以下是类似分析的历史教训，请参考避免重复过去的错误："]
        for m in all_memories:
            correct_str = "✓ 正确" if m.was_correct else "✗ 错误"
            lines.append(
                f"- [{correct_str}] 预测: {m.prediction} → 实际: {m.actual_outcome}"
            )
            lines.append(f"  教训: {m.reflection}")
        return "\n".join(lines)

    def _reflect_all_roles(
        self,
        framework: AnalysisFramework,
        report: InvestmentReport,
        actual_outcome: str,
    ) -> None:
        """对所有角色做反思。"""
        # 构建各角色的预测摘要
        role_predictions = self._extract_role_predictions(report)

        situation = (
            f"公司: {framework.company_name} ({framework.stock_code}), "
            f"行业: {framework.industry}, "
            f"报告日期: {report.report_date.strftime('%Y-%m-%d')}, "
            f"整体评级: {report.investment_rating}"
        )

        for role, prediction in role_predictions.items():
            if not prediction:
                continue
            try:
                reflection_text = self._run_reflection(
                    role, prediction, actual_outcome, situation
                )
                was_correct = self._judge_correctness(
                    report.investment_rating, actual_outcome
                )

                r = Reflection(
                    framework_id=framework.id,
                    role=role,
                    report_id=report.id,
                    situation=situation,
                    prediction=prediction,
                    actual_outcome=actual_outcome,
                    was_correct=was_correct,
                    reflection=reflection_text,
                )
                self.reflection_repo.save(r)
                logger.info(f"  [{role}] 反思完成: {'正确' if was_correct else '错误'}")
            except Exception as e:
                logger.warning(f"  [{role}] 反思失败: {e}")

    def _run_reflection(
        self, role: str, prediction: str, actual_outcome: str, situation: str
    ) -> str:
        """调用 LLM 生成单个角色的反思。"""
        role_labels = {
            "bull": "看多研究员",
            "bear": "看空研究员",
            "financial": "财报分析师",
            "news": "新闻分析师",
            "technical": "技术分析师",
            "risk_advisor": "综合报告（首席投资顾问）",
        }

        user_message = (
            f"## 反思角色\n{role_labels.get(role, role)}\n\n"
            f"## 背景\n{situation}\n\n"
            f"## 上期预测\n{prediction}\n\n"
            f"## 实际结果\n{actual_outcome}\n\n"
            f"请对比预测和实际结果，进行结构化反思。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            prompt_name="reflector",
            model=self.claude.settings.claude_model_heavy,
            max_tokens=2048,
        )

        # 尝试解析 JSON 提取教训摘要
        try:
            json_str = ClaudeClient._extract_json(response)
            data = json.loads(json_str)
            lessons = data.get("lessons", [])
            next_time = data.get("next_time", "")
            attribution = data.get("attribution", "")
            # 拼成紧凑的反思文本
            parts = []
            if attribution:
                parts.append(f"归因: {attribution}")
            if lessons:
                parts.append(f"教训: {'; '.join(lessons)}")
            if next_time:
                parts.append(f"下次: {next_time}")
            return " | ".join(parts) if parts else response.strip()[:500]
        except Exception:
            return response.strip()[:500]

    @staticmethod
    def _extract_role_predictions(report: InvestmentReport) -> dict[str, str]:
        """从报告中提取各角色的预测摘要。"""
        predictions = {}

        # risk_advisor（综合报告）
        predictions["risk_advisor"] = (
            f"评级: {report.investment_rating}, "
            f"理由: {report.rating_rationale}"
        )

        # 从 signal_summary 提取各路信号
        if report.signal_summary:
            s = report.signal_summary
            predictions["news"] = f"新闻信号: {s.news_signal}" if s.news_signal else ""
            predictions["financial"] = f"财报信号: {s.financial_signal}" if s.financial_signal else ""
            predictions["technical"] = f"技术面信号: {s.technical_signal}" if s.technical_signal else ""

            # bull/bear 从 debate_lean 推断
            if s.debate_lean:
                if "看多" in s.debate_lean:
                    predictions["bull"] = f"辩论倾向看多: {s.debate_lean}"
                    predictions["bear"] = f"辩论倾向看多（Bear 论点较弱）: {s.debate_lean}"
                elif "看空" in s.debate_lean:
                    predictions["bull"] = f"辩论倾向看空（Bull 论点较弱）: {s.debate_lean}"
                    predictions["bear"] = f"辩论倾向看空: {s.debate_lean}"
                else:
                    predictions["bull"] = f"辩论平衡: {s.debate_lean}"
                    predictions["bear"] = f"辩论平衡: {s.debate_lean}"

        return predictions

    @staticmethod
    def _judge_correctness(rating: str, actual_outcome: str) -> bool:
        """简单判断：评级方向和实际涨跌是否一致。"""
        bullish_ratings = {"强烈推荐", "推荐"}
        bearish_ratings = {"谨慎", "回避"}

        went_up = "上涨" in actual_outcome or "+" in actual_outcome
        went_down = "下跌" in actual_outcome or "-" in actual_outcome

        if rating in bullish_ratings and went_up:
            return True
        if rating in bearish_ratings and went_down:
            return True
        if rating == "中性" and abs(_extract_pct(actual_outcome)) < 5:
            return True
        return False

    @staticmethod
    def _get_price_change(stock_code: str, report_date: datetime) -> str:
        """获取从报告日期到现在的股价变化。"""
        if not stock_code:
            return ""
        try:
            service = StockHistoryService()
            start = report_date.strftime("%Y%m%d")
            end = datetime.now().strftime("%Y%m%d")
            result = service.fetch_history(stock_code, start, end, period="daily")

            data = result.get("data", [])
            if not data or len(data) < 2:
                return ""

            start_price = data[0]["close"]
            end_price = data[-1]["close"]
            change_pct = (end_price - start_price) / start_price * 100
            days = len(data)

            direction = "上涨" if change_pct > 0 else "下跌" if change_pct < 0 else "持平"
            return (
                f"{direction} {change_pct:+.1f}%（{days}个交易日，"
                f"从 {start_price:.2f} 到 {end_price:.2f}）"
            )
        except Exception as e:
            logger.warning(f"获取股价变化失败 [{stock_code}]: {e}")
            return ""


def _extract_pct(text: str) -> float:
    """从文本中提取百分比数值。"""
    import re
    match = re.search(r'([+-]?\d+\.?\d*)%', text)
    return float(match.group(1)) if match else 0.0
