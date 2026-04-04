"""对话式投研助手核心服务。

整合 Intent Router + Context Assembler + Claude Client，
实现多角色对话、流式输出、数据充足性检查。
"""

import json
import logging
import time
import uuid
from collections.abc import Generator
from datetime import datetime

import anthropic
import openai

from invest_research.config import get_settings
from invest_research.data.database import init_db
from invest_research.data.chat_repo import ChatRepo
from invest_research.models import ChatSession, ChatMessage
from invest_research.services.intent_router import (
    classify_intent, get_role_name, is_screening_intent,
    ROLE_GENERAL, ROLE_FINANCIAL, ROLE_QUANT, ROLE_SENTIMENT, ROLE_DEBATE, ROLE_COMPETITOR,
)
from invest_research.services.context_assembler import ContextAssembler
from invest_research.services.context_compressor import build_compressed_messages
from invest_research.services.data_fetcher import DataFetcher, DATA_TYPE_NAMES

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.assembler = ContextAssembler()
        self.data_fetcher = DataFetcher()
        # 延迟初始化 AI 客户端（按需）
        self._anthropic_client = None
        self._openai_client = None

    def _get_anthropic_client(self):
        if not self._anthropic_client:
            kwargs = {"api_key": self.settings.anthropic_api_key}
            if self.settings.anthropic_base_url:
                kwargs["base_url"] = self.settings.anthropic_base_url
            self._anthropic_client = anthropic.Anthropic(**kwargs)
        return self._anthropic_client

    def _get_openai_client(self):
        if not self._openai_client:
            self._openai_client = openai.OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
        return self._openai_client

    # ===== Session 管理 =====

    def create_session(self, framework_id: int | None = None, model_provider: str = "deepseek") -> ChatSession:
        """创建新对话会话。"""
        session = ChatSession(
            id=uuid.uuid4().hex[:16],
            framework_id=framework_id,
            model_provider=model_provider,
        )
        conn = init_db()
        try:
            repo = ChatRepo(conn)
            repo.save_session(session)
        finally:
            conn.close()
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        conn = init_db()
        try:
            return ChatRepo(conn).get_session(session_id)
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> None:
        conn = init_db()
        try:
            ChatRepo(conn).delete_session(session_id)
        finally:
            conn.close()

    def update_provider(self, session_id: str, provider: str) -> None:
        conn = init_db()
        try:
            ChatRepo(conn).update_session_provider(session_id, provider)
        finally:
            conn.close()

    def get_history(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        conn = init_db()
        try:
            return ChatRepo(conn).get_messages(session_id, limit)
        finally:
            conn.close()

    def list_sessions(self, framework_id: int) -> list[ChatSession]:
        conn = init_db()
        try:
            return ChatRepo(conn).list_sessions_by_framework(framework_id)
        finally:
            conn.close()

    def get_recent_stocks(self, limit: int = 20) -> list[dict]:
        """获取最近对话过的股票列表。"""
        conn = init_db()
        try:
            return ChatRepo(conn).list_recent_frameworks(limit)
        finally:
            conn.close()

    # ===== 对话核心 =====

    def chat(self, session_id: str, user_message: str) -> dict:
        """非流式对话，返回完整响应。"""
        chunks = list(self.chat_stream(session_id, user_message))
        # 从流式块中组装完整响应
        content_parts = []
        result = {}
        for chunk in chunks:
            if chunk.get("type") == "text":
                content_parts.append(chunk["content"])
            elif chunk.get("type") == "meta":
                result.update(chunk)
        result["content"] = "".join(content_parts)
        return result

    def chat_stream(self, session_id: str, user_message: str) -> Generator[dict, None, None]:
        """流式对话（两轮架构），全程 yield 事件。

        Yields:
            {"type": "routing", "specialist": str, "role_name": str}
            {"type": "analyzing"}
            {"type": "fetching", "items": [{"key": str, "name": str}, ...]}
            {"type": "fetched", "item": str, "name": str}
            {"type": "meta", "specialist": str, "role_name": str, "data_refs": list, "stale_warnings": list}
            {"type": "text", "content": str}  (多次)
            {"type": "done"}
        """
        # 1. 获取 session
        conn = init_db()
        try:
            repo = ChatRepo(conn)
            session = repo.get_session(session_id)
            if not session:
                yield {"type": "error", "content": "会话不存在"}
                return

            # 2. 保存用户消息
            user_msg = ChatMessage(
                session_id=session_id,
                role="user",
                content=user_message,
            )
            repo.save_message(user_msg)

            # 3. 意图路由
            from invest_research.services.claude_client import ClaudeClient
            claude_client = ClaudeClient(self.settings)
            is_market_session = session.framework_id is None
            role = ROLE_GENERAL if is_market_session else classify_intent(user_message, claude_client)

            yield {
                "type": "routing",
                "specialist": role,
                "role_name": "市场分析师" if is_market_session else get_role_name(role),
            }

            # 4. Pass 1: 数据需求分析
            yield {"type": "analyzing"}

            if is_market_session:
                # 市场级对话：只有筛选类数据
                inventory = self.assembler.build_market_inventory()
                framework = None
                report = None
                # 市场级对话默认需要 market_screening
                fetch_keys = ["market_screening"] if is_screening_intent(user_message) else self._analyze_data_needs(
                    claude_client, user_message, role, inventory, session.model_provider,
                )
            else:
                inventory = self.assembler.build_data_inventory(session.framework_id)
                framework = inventory["framework"]
                report = inventory["report"]
                # 单股对话中也可能有筛选意图
                fetch_keys = self._analyze_data_needs(
                    claude_client, user_message, role, inventory, session.model_provider,
                )

            # 5. 按需拉取数据
            extra_data = {}
            if fetch_keys:
                items = [{"key": k, "name": DATA_TYPE_NAMES.get(k, k)} for k in fetch_keys]
                yield {"type": "fetching", "items": items}

                for key in fetch_keys:
                    _, text = self.data_fetcher.fetch_one(
                        key, framework, report, user_message=user_message,
                    )
                    if text:
                        extra_data[key] = text
                    yield {"type": "fetched", "item": key, "name": DATA_TYPE_NAMES.get(key, key)}

            # 6. 组装完整上下文（标准 + 额外数据）
            if is_market_session:
                ctx = self.assembler.assemble_market_context(extra_data)
            elif extra_data:
                ctx = self.assembler.assemble_with_extra(session.framework_id, role, extra_data)
            else:
                ctx = self.assembler.assemble(session.framework_id, role)

            # 7. 评估数据建议（用户可操作的改进建议）
            suggestions = [] if is_market_session else self._evaluate_data_suggestions(
                inventory, ctx, role, user_message,
            )

            # 8. 发送 meta
            yield {
                "type": "meta",
                "specialist": role,
                "role_name": get_role_name(role),
                "data_refs": ctx.data_refs,
                "stale_warnings": ctx.stale_warnings,
                "suggestions": suggestions,
            }

            # 9. 构建消息列表（含自动压缩）— Pass 2 正式回答
            all_messages = repo.get_messages(session_id, limit=100)
            if is_market_session:
                prompt_name = "chat_market"
            else:
                prompt_name = f"chat_{role}"
            system_prompt = claude_client._load_prompt(prompt_name)

            if ctx.context_text:
                system_prompt += f"\n\n---\n\n# 本地数据（请基于以下数据回答用户问题）\n\n{ctx.context_text}"

            messages = build_compressed_messages(all_messages, claude_client)

            if not messages or messages[-1]["content"] != user_message:
                messages.append({"role": "user", "content": user_message})

            # 10. 流式调用 AI（Pass 2）
            full_response = []
            provider = session.model_provider

            try:
                if provider == "deepseek":
                    for chunk_text in self._stream_deepseek(messages, system_prompt):
                        full_response.append(chunk_text)
                        yield {"type": "text", "content": chunk_text}
                else:
                    for chunk_text in self._stream_anthropic(messages, system_prompt):
                        full_response.append(chunk_text)
                        yield {"type": "text", "content": chunk_text}
            except Exception as e:
                logger.error(f"AI 调用失败: {e}")
                error_msg = f"AI 服务调用失败: {str(e)[:100]}"
                yield {"type": "text", "content": error_msg}
                full_response.append(error_msg)

            # 11. 保存 assistant 消息
            assistant_content = "".join(full_response)
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                specialist=role,
                data_refs=ctx.data_refs,
            )
            repo.save_message(assistant_msg)

            yield {"type": "done"}

        finally:
            conn.close()

    def _analyze_data_needs(
        self,
        claude_client,
        user_message: str,
        role: str,
        inventory: dict,
        model_provider: str,
    ) -> list[str]:
        """Pass 1: 用轻量模型分析需要补充哪些数据。"""
        available = inventory.get("available", {})
        missing = inventory.get("missing", {})

        # 如果没有可补充的数据，跳过 Pass 1
        if not missing:
            logger.info("Pass 1 跳过: 无可补充数据")
            return []

        # 构建 prompt
        available_text = "\n".join(f"- {k}: {v}" for k, v in available.items()) or "（无）"
        missing_text = "\n".join(f"- {k}: {v}" for k, v in missing.items()) or "（无）"

        prompt_template = claude_client._load_prompt("data_needs")
        # prompt 中用 {{}} 转义普通花括号，先替换占位符再还原
        prompt = (prompt_template
            .replace("{{role_name}}", get_role_name(role))
            .replace("{{user_message}}", user_message)
            .replace("{{available_data}}", available_text)
            .replace("{{missing_data}}", missing_text)
            .replace("{{", "{").replace("}}", "}")
        )

        try:
            result = claude_client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            # 解析 JSON
            json_str = claude_client._extract_json(result)
            parsed = json.loads(json_str)
            fetch_keys = parsed.get("fetch", [])
            reason = parsed.get("reason", "")

            # 过滤：只保留 missing 中存在的 key
            valid_keys = [k for k in fetch_keys if k in missing]

            if valid_keys:
                logger.info(f"Pass 1 需要补充: {valid_keys} (原因: {reason})")
            else:
                logger.info(f"Pass 1: 数据充足 ({reason})")
            return valid_keys

        except Exception as e:
            logger.warning(f"Pass 1 数据需求分析失败: {e}，跳过补数据")
            return []

    def export_session(self, session_id: str) -> str | None:
        """导出对话为 Markdown 文本。返回 None 表示会话不存在。"""
        conn = init_db()
        try:
            repo = ChatRepo(conn)
            session = repo.get_session(session_id)
            if not session:
                return None

            messages = repo.get_messages(session_id, limit=500)

            # 获取公司信息
            if session.framework_id:
                from invest_research.data.framework_repo import FrameworkRepo
                fw = FrameworkRepo(conn).get_by_id(session.framework_id)
                company = f"{fw.company_name} ({fw.stock_code})" if fw else "未知股票"
            else:
                company = "全市场分析"

            # 构建 Markdown
            lines = [
                f"# {company} 投研对话记录",
                "",
                f"- 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                f"- 对话模型: {'Claude' if session.model_provider == 'anthropic' else 'DeepSeek'}",
                f"- 消息数: {len(messages)}",
                "",
                "---",
                "",
            ]

            role_names = {
                "general": "综合顾问", "financial": "财务分析师",
                "quant": "量化分析师", "sentiment": "情绪分析师",
                "debate": "多空辩手", "competitor": "竞品分析师",
            }

            for msg in messages:
                time_str = msg.created_at.strftime('%H:%M') if msg.created_at else ""
                if msg.role == "user":
                    lines.append(f"## 用户 ({time_str})")
                elif msg.role == "assistant":
                    role_label = role_names.get(msg.specialist, msg.specialist or "AI")
                    lines.append(f"## {role_label} ({time_str})")
                else:
                    lines.append(f"## 系统 ({time_str})")
                lines.append("")
                lines.append(msg.content)
                lines.append("")
                lines.append("---")
                lines.append("")

            return "\n".join(lines)
        finally:
            conn.close()

    def _evaluate_data_suggestions(
        self,
        inventory: dict,
        ctx,
        role: str,
        user_message: str,
    ) -> list[dict]:
        """评估数据充足性，返回可操作的建议列表。

        只在数据有明显缺陷且用户操作能改善时才返回建议。
        """
        suggestions = []
        report = inventory.get("report")
        framework = inventory.get("framework")

        if not framework:
            return suggestions

        # 1. 报告过期 → 建议重新研究
        if report and report.report_date:
            from invest_research.services.context_assembler import REPORT_STALE_DAYS
            age_days = (datetime.now() - report.report_date).days
            if age_days > REPORT_STALE_DAYS:
                suggestions.append({
                    "key": "regenerate_report",
                    "message": f"投研报告已过期（{age_days}天前，{report.report_date.strftime('%Y-%m-%d')}），重新研究可获取最新分析",
                    "action": "regenerate_report",
                    "severity": "warning",
                })

        # 2. 无报告 → 建议生成报告
        if not report:
            suggestions.append({
                "key": "no_report",
                "message": "该股票暂无投研报告，生成报告后对话质量会大幅提升",
                "action": "regenerate_report",
                "severity": "info",
            })

        # 3. 财务数据过期 → 建议刷新（仅财务相关角色/问题）
        if role in ("financial", "general"):
            has_financial = bool(framework.financial_summary)
            if has_financial and framework.financial_fetched_at:
                from invest_research.services.context_assembler import FINANCIAL_STALE_DAYS
                fetched = framework.financial_fetched_at
                if isinstance(fetched, str):
                    fetched = datetime.fromisoformat(fetched)
                age_days = (datetime.now() - fetched).days
                if age_days > FINANCIAL_STALE_DAYS:
                    suggestions.append({
                        "key": "refresh_financial",
                        "message": f"财报数据已过期（{age_days}天前获取），可刷新获取最新数据",
                        "action": "refresh_financial",
                        "severity": "info",
                    })
            elif not has_financial:
                suggestions.append({
                    "key": "refresh_financial",
                    "message": "暂无财报数据，获取后可提供更专业的财务分析",
                    "action": "refresh_financial",
                    "severity": "info",
                })

        return suggestions

    # ===== 流式 AI 调用 =====

    def _stream_anthropic(self, messages: list[dict], system_prompt: str) -> Generator[str, None, None]:
        """Anthropic Claude 流式输出。"""
        client = self._get_anthropic_client()
        max_retries = self.settings.claude_max_retries

        for attempt in range(max_retries):
            try:
                with client.messages.stream(
                    model=self.settings.claude_model_light,
                    max_tokens=self.settings.claude_max_tokens,
                    system=system_prompt,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        yield text
                return
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Anthropic 速率限制，等待 {wait}s (第 {attempt + 1} 次)")
                time.sleep(wait)
            except anthropic.APIError as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                logger.warning(f"Anthropic API 错误: {e}，等待 {wait}s")
                time.sleep(wait)

        raise RuntimeError("Anthropic API 调用失败")

    def _stream_deepseek(self, messages: list[dict], system_prompt: str) -> Generator[str, None, None]:
        """DeepSeek 流式输出（OpenAI 兼容）。"""
        client = self._get_openai_client()

        oai_messages = [{"role": "system", "content": system_prompt}]
        oai_messages.extend(messages)

        for attempt in range(self.settings.claude_max_retries):
            try:
                stream = client.chat.completions.create(
                    model=self.settings.deepseek_model_light,
                    messages=oai_messages,
                    max_tokens=min(self.settings.claude_max_tokens, 8192),
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except openai.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"DeepSeek 速率限制，等待 {wait}s")
                time.sleep(wait)
            except openai.APIError as e:
                if attempt == self.settings.claude_max_retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                logger.warning(f"DeepSeek API 错误: {e}，等待 {wait}s")
                time.sleep(wait)

        raise RuntimeError("DeepSeek API 调用失败")
