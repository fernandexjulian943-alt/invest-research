import json
import logging
import time
from pathlib import Path

import anthropic

from invest_research.config import get_settings

logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def _load_prompt(self, prompt_name: str) -> str:
        prompt_path = self.settings.prompts_dir / f"{prompt_name}.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def chat(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        prompt_name: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if prompt_name and not system_prompt:
            system_prompt = self._load_prompt(prompt_name)

        model = model or self.settings.claude_model_light
        max_tokens = max_tokens or self.settings.claude_max_tokens

        for attempt in range(self.settings.claude_max_retries):
            try:
                kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
                if system_prompt:
                    kwargs["system"] = system_prompt
                response = self.client.messages.create(**kwargs)
                return response.content[0].text
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"速率限制，等待 {wait} 秒后重试 (第 {attempt + 1} 次)")
                time.sleep(wait)
            except anthropic.APIError as e:
                if attempt == self.settings.claude_max_retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                logger.warning(f"API 错误: {e}，等待 {wait} 秒后重试 (第 {attempt + 1} 次)")
                time.sleep(wait)
        raise RuntimeError("Claude API 调用失败，已达最大重试次数")

    def chat_structured(
        self,
        messages: list[dict],
        output_schema: type,
        system_prompt: str | None = None,
        prompt_name: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ):
        schema_hint = (
            f"\n\n请严格按以下 JSON 格式输出，不要包含其他内容:\n"
            f"```json\n{json.dumps(output_schema.model_json_schema(), ensure_ascii=False, indent=2)}\n```"
        )

        if prompt_name and not system_prompt:
            system_prompt = self._load_prompt(prompt_name)
        if system_prompt:
            system_prompt += schema_hint
        else:
            system_prompt = schema_hint

        raw = self.chat(
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
        )

        json_str = self._extract_json(raw)
        return output_schema.model_validate_json(json_str)

    @staticmethod
    def _extract_json(text: str) -> str:
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.index("```", start)
            return text[start:end].strip()
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return text[start:end].strip()
        # 尝试直接找 JSON 对象
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return text[start:end]
        return text
