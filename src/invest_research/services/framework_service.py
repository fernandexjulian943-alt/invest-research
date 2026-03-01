import json
import logging

from invest_research.models import AnalysisFramework
from invest_research.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

FRAMEWORK_COMPLETE_MARKER = "[FRAMEWORK_COMPLETE]"


class FrameworkService:
    def __init__(self, claude_client: ClaudeClient):
        self.claude = claude_client

    def build_framework(
        self,
        company_name: str,
        user_input_fn,
        display_fn,
    ) -> AnalysisFramework:
        messages = [
            {"role": "user", "content": f"我想为 {company_name} 建立投资分析框架。请开始引导我。"}
        ]

        while True:
            response = self.claude.chat(
                messages=messages,
                prompt_name="framework_builder",
                model=self.claude.settings.claude_model_heavy,
            )

            if FRAMEWORK_COMPLETE_MARKER in response:
                display_fn(response.split(FRAMEWORK_COMPLETE_MARKER)[0].strip())
                framework = self._parse_framework(response)
                if framework:
                    return framework
                display_fn("框架解析失败，请继续补充信息。")
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": "请重新输出完整的框架 JSON。"})
                continue

            display_fn(response)
            messages.append({"role": "assistant", "content": response})

            user_reply = user_input_fn()
            if not user_reply or user_reply.strip().lower() in ("quit", "exit", "q"):
                # 用户想退出，让 AI 根据已有信息生成框架
                messages.append({
                    "role": "user",
                    "content": "请根据已有的信息生成完整的分析框架 JSON。",
                })
                response = self.claude.chat(
                    messages=messages,
                    prompt_name="framework_builder",
                    model=self.claude.settings.claude_model_heavy,
                )
                display_fn(response.split(FRAMEWORK_COMPLETE_MARKER)[0].strip() if FRAMEWORK_COMPLETE_MARKER in response else response)
                framework = self._parse_framework(response)
                if framework:
                    return framework
                raise ValueError("无法生成有效的分析框架")

            messages.append({"role": "user", "content": user_reply})

    def build_framework_auto(self, company_name: str) -> AnalysisFramework:
        """一次性自动生成分析框架，无需多轮对话。"""
        messages = [
            {"role": "user", "content": f"请为 {company_name} 生成投资分析框架。"}
        ]
        response = self.claude.chat(
            messages=messages,
            prompt_name="framework_builder_auto",
            model=self.claude.settings.claude_model_light,
        )
        framework = self._parse_framework(response)
        if framework:
            return framework
        raise ValueError(f"无法为 {company_name} 自动生成分析框架")

    @staticmethod
    def _parse_framework(text: str) -> AnalysisFramework | None:
        try:
            if "```json" in text:
                start = text.index("```json") + len("```json")
                end = text.index("```", start)
                json_str = text[start:end].strip()
            elif "```" in text:
                start = text.index("```") + 3
                end = text.index("```", start)
                json_str = text[start:end].strip()
            else:
                brace_start = text.find("{")
                brace_end = text.rfind("}") + 1
                if brace_start == -1 or brace_end <= brace_start:
                    return None
                json_str = text[brace_start:brace_end]

            data = json.loads(json_str)
            return AnalysisFramework(**data)
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            logger.error(f"框架 JSON 解析失败: {e}")
            return None
