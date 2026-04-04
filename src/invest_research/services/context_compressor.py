"""对话历史压缩器。

参考 Claude Code 的上下文压缩思路：
- 近期消息保持原文（最近 N 轮）
- 早期消息由 LLM 摘要为结构化上下文
- 摘要注入为首条 system 消息，对用户透明

压缩策略：
1. 统计对话消息总 token（粗估：中文 1 字 ≈ 2 token，英文 1 词 ≈ 1.3 token）
2. 超过阈值时触发压缩
3. 保留最近 KEEP_RECENT 轮对话原文
4. 更早的消息交给 LLM 生成摘要
5. 摘要存入 DB 替换原始消息
"""

import logging
from invest_research.models import ChatMessage

logger = logging.getLogger(__name__)

# 配置
TOKEN_BUDGET = 3000        # 对话历史 token 预算（不含 system prompt 和数据上下文）
KEEP_RECENT = 6            # 保留最近 N 条消息原文（3 轮对话）
COMPRESS_TRIGGER = 12      # 消息数超过此值时检查是否需要压缩

COMPRESS_PROMPT = """你是对话摘要助手。将以下投资对话浓缩为结构化摘要，保留关键信息。

## 必须保留
- 用户提出的核心问题和关注点
- AI 给出的关键结论、数据和建议
- 已确认的投资偏好或决策
- 用户表达的疑虑或分歧

## 可以压缩
- 寒暄和重复内容
- 冗长的分析过程（只保留结论）
- 格式化的数据展示（保留关键数字）

## 输出格式
用简洁的条目列出要点，每条一行，不超过 300 字总量。格式：
- [用户] 关注 xxx
- [分析] 结论是 xxx（数据：xxx）
- [决策] 用户倾向 xxx

## 待压缩的对话
"""


def estimate_tokens(text: str) -> int:
    """粗估 token 数。中文字符按 2 token，其他按 1.3 token/词。"""
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - cn_chars
    return int(cn_chars * 2 + other_chars * 0.4)


def estimate_messages_tokens(messages: list[ChatMessage]) -> int:
    """估算消息列表的总 token 数。"""
    return sum(estimate_tokens(m.content) for m in messages)


def needs_compression(messages: list[ChatMessage]) -> bool:
    """判断是否需要压缩。"""
    if len(messages) < COMPRESS_TRIGGER:
        return False
    return estimate_messages_tokens(messages) > TOKEN_BUDGET


def build_compressed_messages(
    all_messages: list[ChatMessage],
    claude_client,
) -> list[dict]:
    """构建压缩后的消息列表。

    返回 Anthropic/OpenAI 格式的 messages 列表。
    如果不需要压缩，直接返回原始消息。
    """
    if not needs_compression(all_messages):
        # 不需要压缩，直接返回
        return [
            {"role": m.role, "content": m.content}
            for m in all_messages
            if m.role in ("user", "assistant")
        ]

    # 分割：早期消息 vs 近期消息
    early = all_messages[:-KEEP_RECENT]
    recent = all_messages[-KEEP_RECENT:]

    logger.info(
        f"压缩对话: {len(all_messages)} 条消息 → "
        f"压缩 {len(early)} 条 + 保留 {len(recent)} 条"
    )

    # 用 LLM 压缩早期消息
    summary = _summarize_messages(early, claude_client)

    # 构建最终消息列表
    result = []
    if summary:
        result.append({
            "role": "user",
            "content": f"[对话摘要 - 之前的讨论要点]\n{summary}",
        })
        result.append({
            "role": "assistant",
            "content": "好的，我已了解之前的讨论内容，会在后续回答中参考这些要点。",
        })

    for m in recent:
        if m.role in ("user", "assistant"):
            result.append({"role": m.role, "content": m.content})

    compressed_tokens = sum(estimate_tokens(m["content"]) for m in result)
    logger.info(f"压缩后 token 估算: {compressed_tokens}")

    return result


def _summarize_messages(messages: list[ChatMessage], claude_client) -> str:
    """用 LLM 摘要早期消息。"""
    # 格式化对话文本
    conversation_text = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}({m.specialist or 'general'}): {m.content[:500]}"
        for m in messages
        if m.role in ("user", "assistant")
    )

    if not conversation_text.strip():
        return ""

    try:
        summary = claude_client.chat(
            messages=[{"role": "user", "content": COMPRESS_PROMPT + conversation_text}],
            max_tokens=400,
        )
        return summary.strip()
    except Exception as e:
        logger.warning(f"对话压缩失败，回退为简单截断: {e}")
        return _fallback_summary(messages)


def _fallback_summary(messages: list[ChatMessage]) -> str:
    """LLM 摘要失败时的回退方案：提取关键消息的首句。"""
    points = []
    for m in messages:
        if m.role == "user":
            first_line = m.content.split("\n")[0][:100]
            points.append(f"- [用户] {first_line}")
        elif m.role == "assistant" and m.content:
            first_line = m.content.split("\n")[0][:100]
            role_name = m.specialist or "助手"
            points.append(f"- [{role_name}] {first_line}")
    # 只保留最多 10 条要点
    return "\n".join(points[:10])
