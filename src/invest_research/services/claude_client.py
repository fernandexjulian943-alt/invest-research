import json
import logging
import time
from pathlib import Path

import anthropic
import openai

from invest_research.config import get_settings

logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.provider = self.settings.ai_provider.lower()

        if self.provider == "deepseek":
            self.openai_client = openai.OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
            logger.info("AI 后端: DeepSeek")
        else:
            kwargs = {"api_key": self.settings.anthropic_api_key}
            if self.settings.anthropic_base_url:
                kwargs["base_url"] = self.settings.anthropic_base_url
            self.anthropic_client = anthropic.Anthropic(**kwargs)
            logger.info("AI 后端: Anthropic")

    def _resolve_model(self, model: str | None) -> str:
        """根据 provider 解析模型名称。"""
        if self.provider == "deepseek":
            if model and ("heavy" in model or "opus" in model):
                return self.settings.deepseek_model_heavy
            return self.settings.deepseek_model_light
        return model or self.settings.claude_model_light

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

        resolved_model = self._resolve_model(model)
        max_tokens = max_tokens or self.settings.claude_max_tokens

        if self.provider == "deepseek":
            return self._chat_deepseek(messages, system_prompt, resolved_model, max_tokens)
        return self._chat_anthropic(messages, system_prompt, resolved_model, max_tokens)

    def _chat_anthropic(
        self, messages: list[dict], system_prompt: str | None, model: str, max_tokens: int
    ) -> str:
        for attempt in range(self.settings.claude_max_retries):
            try:
                kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
                if system_prompt:
                    kwargs["system"] = system_prompt
                response = self.anthropic_client.messages.create(**kwargs)
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
        raise RuntimeError("Anthropic API 调用失败，已达最大重试次数")

    def _chat_deepseek(
        self, messages: list[dict], system_prompt: str | None, model: str, max_tokens: int
    ) -> str:
        # 构建 OpenAI 格式消息列表
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        oai_messages.extend(messages)

        for attempt in range(self.settings.claude_max_retries):
            try:
                # DeepSeek chat 模型 max_tokens 上限 8192
                capped_tokens = min(max_tokens, 8192)
                kwargs = {"model": model, "messages": oai_messages, "max_tokens": capped_tokens}
                # deepseek-reasoner 不支持 max_tokens，改用 max_completion_tokens
                if model == "deepseek-reasoner":
                    kwargs.pop("max_tokens")
                    kwargs["max_completion_tokens"] = capped_tokens
                response = self.openai_client.chat.completions.create(**kwargs)
                return response.choices[0].message.content
            except openai.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"DeepSeek 速率限制，等待 {wait} 秒后重试 (第 {attempt + 1} 次)")
                time.sleep(wait)
            except openai.APIError as e:
                if attempt == self.settings.claude_max_retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                logger.warning(f"DeepSeek API 错误: {e}，等待 {wait} 秒后重试 (第 {attempt + 1} 次)")
                time.sleep(wait)
        raise RuntimeError("DeepSeek API 调用失败，已达最大重试次数")

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
        # 尝试提取 ```json ... ``` 块
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()
        # 尝试提取 ``` ... ``` 块
        if "```" in text:
            start = text.index("```") + 3
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()
        # 尝试直接找 JSON 对象
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return text[start:end]
        return text
