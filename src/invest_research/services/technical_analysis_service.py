import json
import logging

import pandas as pd

from invest_research.models import AnalysisFramework
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class TechnicalAnalysisService:
    """基于历史价格数据计算技术指标并调用 AI 解读。"""

    def __init__(self, claude_client: ClaudeClient):
        self.claude = claude_client

    def analyze(self, framework: AnalysisFramework, history_data: dict) -> dict:
        """计算技术指标后调用 AI 分析，返回结构化结论。"""
        data_list = history_data.get("data", [])
        if not data_list or len(data_list) < 20:
            return self._empty_result("历史价格数据不足，无法进行技术分析")

        indicators_text = self._compute_indicators(data_list)
        framework_context = self._build_context(framework)

        user_message = (
            f"## 分析框架\n{framework_context}\n\n"
            f"## 技术指标数据\n{indicators_text}\n\n"
            f"请基于以上技术指标数据，输出结构化的技术分析结论。"
            f"注意输出的 JSON 中所有字符串值内的双引号必须用反斜杠转义。"
        )

        response = self.claude.chat(
            messages=[{"role": "user", "content": user_message}],
            prompt_name="technical_analyst",
            model=self.claude.settings.claude_model_heavy,
            max_tokens=4096,
        )

        return self._parse_result(response)

    def format_for_report(self, result: dict) -> str:
        """格式化为报告文本。"""
        if not result or "数据不足" in result.get("summary", ""):
            return ""

        parts = []

        trend = result.get("trend", "")
        strength = result.get("trend_strength", "")
        if trend:
            parts.append(f"【趋势】{trend}（强度: {strength}）")

        levels = result.get("key_levels", {})
        support = levels.get("support", [])
        resistance = levels.get("resistance", [])
        if support or resistance:
            parts.append(f"【关键价位】支撑: {support}  阻力: {resistance}")

        indicators = result.get("indicators", {})
        if indicators:
            parts.append("【技术指标信号】")
            for k, v in indicators.items():
                label = {"ma_signal": "均线", "rsi_signal": "RSI", "macd_signal": "MACD", "volume_signal": "成交量"}.get(k, k)
                parts.append(f"  {label}: {v}")

        pattern = result.get("pattern", "")
        if pattern and pattern != "无":
            parts.append(f"【形态】{pattern}")

        signal = result.get("signal", "neutral")
        confidence = result.get("confidence", 0.0)
        if signal:
            # 兼容旧版中文信号
            signal_normalized = self._normalize_signal(signal)
            confidence_normalized = self._normalize_confidence(confidence)
            parts.append(f"【综合信号】{signal}（信心: {confidence}）")
            parts.append(f"【信号】signal: {signal_normalized}, confidence: {confidence_normalized}")

        summary = result.get("summary", "")
        if summary:
            parts.append(f"【总结】{summary}")

        return "\n".join(parts)

    @staticmethod
    def _compute_indicators(data_list: list[dict]) -> str:
        """用 pandas 计算技术指标，格式化为文本。"""
        df = pd.DataFrame(data_list)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # 均线
        for period in [5, 10, 20, 60]:
            df[f"MA{period}"] = close.rolling(period).mean().round(2)

        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-10)
        df["RSI"] = (100 - 100 / (1 + rs)).round(2)

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        df["DIF"] = (ema12 - ema26).round(4)
        df["DEA"] = df["DIF"].ewm(span=9).mean().round(4)
        df["MACD_hist"] = ((df["DIF"] - df["DEA"]) * 2).round(4)

        # 布林带 (20, 2)
        df["BOLL_mid"] = close.rolling(20).mean().round(2)
        std20 = close.rolling(20).std()
        df["BOLL_upper"] = (df["BOLL_mid"] + 2 * std20).round(2)
        df["BOLL_lower"] = (df["BOLL_mid"] - 2 * std20).round(2)

        # 成交量均线
        df["VOL_MA5"] = volume.rolling(5).mean().round(0)
        df["VOL_MA20"] = volume.rolling(20).mean().round(0)

        # 取最近 60 个交易日的摘要
        recent = df.tail(60)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest

        lines = []
        lines.append(f"数据范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}，共 {len(df)} 个交易日")
        lines.append(f"最新收盘: {latest['close']}  最高: {latest['high']}  最低: {latest['low']}")
        lines.append("")

        # 均线当前值
        lines.append("=== 均线 ===")
        for period in [5, 10, 20, 60]:
            val = latest.get(f"MA{period}")
            if pd.notna(val):
                lines.append(f"MA{period}: {val}")
        # 均线排列判断
        ma_vals = [latest.get(f"MA{p}") for p in [5, 10, 20, 60]]
        if all(pd.notna(v) for v in ma_vals):
            if ma_vals[0] > ma_vals[1] > ma_vals[2] > ma_vals[3]:
                lines.append("排列: 多头排列（MA5 > MA10 > MA20 > MA60）")
            elif ma_vals[0] < ma_vals[1] < ma_vals[2] < ma_vals[3]:
                lines.append("排列: 空头排列（MA5 < MA10 < MA20 < MA60）")
            else:
                lines.append("排列: 缠绕/混合")

        lines.append("")
        lines.append("=== RSI (14) ===")
        lines.append(f"当前: {latest.get('RSI', 'N/A')}")
        # 近5日趋势
        rsi_recent = recent["RSI"].dropna().tail(5).tolist()
        if rsi_recent:
            lines.append(f"近5日: {[round(v, 1) for v in rsi_recent]}")

        lines.append("")
        lines.append("=== MACD ===")
        lines.append(f"DIF: {latest.get('DIF', 'N/A')}  DEA: {latest.get('DEA', 'N/A')}  柱状图: {latest.get('MACD_hist', 'N/A')}")
        # 金叉/死叉检测
        if pd.notna(latest.get("DIF")) and pd.notna(prev.get("DIF")):
            if prev["DIF"] <= prev["DEA"] and latest["DIF"] > latest["DEA"]:
                lines.append("信号: 刚发生金叉")
            elif prev["DIF"] >= prev["DEA"] and latest["DIF"] < latest["DEA"]:
                lines.append("信号: 刚发生死叉")
        # 柱状图方向
        hist_recent = recent["MACD_hist"].dropna().tail(5).tolist()
        if hist_recent:
            lines.append(f"柱状图近5日: {[round(v, 4) for v in hist_recent]}")

        lines.append("")
        lines.append("=== 布林带 (20, 2) ===")
        lines.append(f"上轨: {latest.get('BOLL_upper', 'N/A')}  中轨: {latest.get('BOLL_mid', 'N/A')}  下轨: {latest.get('BOLL_lower', 'N/A')}")
        if pd.notna(latest.get("BOLL_upper")):
            pos = "接近上轨" if latest["close"] >= latest["BOLL_upper"] * 0.98 else \
                  "接近下轨" if latest["close"] <= latest["BOLL_lower"] * 1.02 else \
                  "中轨附近" if abs(latest["close"] - latest["BOLL_mid"]) / latest["BOLL_mid"] < 0.02 else \
                  "中轨与上轨之间" if latest["close"] > latest["BOLL_mid"] else "中轨与下轨之间"
            lines.append(f"位置: {pos}")

        lines.append("")
        lines.append("=== 成交量 ===")
        lines.append(f"最新成交量: {latest.get('volume', 'N/A')}  5日均量: {latest.get('VOL_MA5', 'N/A')}  20日均量: {latest.get('VOL_MA20', 'N/A')}")
        if pd.notna(latest.get("VOL_MA5")) and pd.notna(latest.get("VOL_MA20")) and latest["VOL_MA20"] > 0:
            vol_ratio = latest["volume"] / latest["VOL_MA20"]
            lines.append(f"量比(vs 20日均量): {vol_ratio:.2f}")

        # 近期价格走势摘要（最近20日的高低收）
        lines.append("")
        lines.append("=== 近20日价格走势 ===")
        last20 = recent.tail(20)
        for _, row in last20.iterrows():
            lines.append(f"{row['date'].strftime('%m-%d')} O:{row['open']} H:{row['high']} L:{row['low']} C:{row['close']} V:{row['volume']}")

        return "\n".join(lines)

    @staticmethod
    def _build_context(framework: AnalysisFramework) -> str:
        lines = [
            f"目标公司: {framework.company_name} ({framework.stock_code})",
            f"行业: {framework.industry}",
        ]
        if framework.investment_strategy and framework.investment_strategy != "balanced":
            strategy_labels = {"high_dividend": "高分红稳定型", "high_growth": "高增长爆发型"}
            lines.append(f"投资策略: {strategy_labels.get(framework.investment_strategy, framework.investment_strategy)}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_signal(signal: str) -> str:
        """将中文或英文信号统一为标准英文枚举。"""
        mapping = {"看多": "bullish", "看空": "bearish", "中性": "neutral"}
        return mapping.get(signal, signal if signal in ("bullish", "bearish", "neutral") else "neutral")

    @staticmethod
    def _normalize_confidence(confidence) -> float:
        """将文字或数值 confidence 统一为 0-1 浮点数。"""
        if isinstance(confidence, (int, float)):
            return min(max(float(confidence), 0.0), 1.0)
        mapping = {"高": 0.8, "中": 0.5, "低": 0.2}
        if isinstance(confidence, str):
            if confidence in mapping:
                return mapping[confidence]
            try:
                return min(max(float(confidence), 0.0), 1.0)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _extract_signal(result: dict) -> tuple[str, float]:
        """从分析结果中提取标准化信号。"""
        signal = TechnicalAnalysisService._normalize_signal(result.get("signal", "neutral"))
        confidence = TechnicalAnalysisService._normalize_confidence(result.get("confidence", 0.0))
        return signal, confidence

    @staticmethod
    def _parse_result(response: str) -> dict:
        try:
            json_str = ClaudeClient._extract_json(response)
            return json.loads(json_str)
        except Exception as e:
            logger.warning(f"技术分析 JSON 解析失败: {e}")
            return {
                "trend": "", "trend_strength": "",
                "key_levels": {"support": [], "resistance": []},
                "indicators": {},
                "pattern": "", "signal": "neutral", "confidence": 0.2,
                "summary": response.strip()[:500],
            }

    @staticmethod
    def _empty_result(reason: str) -> dict:
        return {
            "trend": "", "trend_strength": "",
            "key_levels": {"support": [], "resistance": []},
            "indicators": {},
            "pattern": "", "signal": "neutral", "confidence": 0.0,
            "summary": reason,
        }
