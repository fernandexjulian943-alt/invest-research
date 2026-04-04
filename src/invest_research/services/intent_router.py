"""意图路由器：规则优先 + LLM 兜底，将用户问题分配到对应专家角色。"""

import logging
import re

logger = logging.getLogger(__name__)

# 专家角色定义
ROLE_GENERAL = "general"
ROLE_FINANCIAL = "financial"
ROLE_QUANT = "quant"
ROLE_SENTIMENT = "sentiment"
ROLE_DEBATE = "debate"
ROLE_COMPETITOR = "competitor"

# 角色中文名映射
ROLE_NAMES = {
    ROLE_GENERAL: "综合顾问",
    ROLE_FINANCIAL: "财务分析师",
    ROLE_QUANT: "量化分析师",
    ROLE_SENTIMENT: "情绪分析师",
    ROLE_DEBATE: "多空辩手",
    ROLE_COMPETITOR: "竞品分析师",
}

# 关键词→角色映射（按优先级排列）
INTENT_RULES: dict[str, list[str]] = {
    ROLE_FINANCIAL: [
        "财报", "营收", "利润", "净利", "毛利", "净利率", "毛利率",
        "ROE", "ROA", "ROIC", "现金流", "资产负债", "存货",
        "PE", "PB", "市盈率", "市净率", "估值",
        "revenue", "profit", "earnings", "balance sheet", "cash flow",
        "财务", "盈利", "亏损", "负债", "应收", "分红", "股息",
        "成本", "费用", "研发投入", "capex",
    ],
    ROLE_QUANT: [
        "技术面", "技术分析", "K线", "k线", "均线", "MA", "MACD", "RSI",
        "布林", "支撑", "阻力", "量价", "成交量", "换手",
        "趋势", "价格走势", "买点", "卖点", "形态",
        "突破", "回调", "反弹", "超买", "超卖",
        "日线", "周线", "月线",
    ],
    ROLE_SENTIMENT: [
        "情绪", "舆情", "雪球", "散户", "大V", "市场情绪",
        "看多", "看空", "讨论", "评论", "观点",
        "恐慌", "贪婪", "乐观", "悲观",
    ],
    ROLE_DEBATE: [
        "看涨理由", "看跌理由", "多空", "bull", "bear",
        "为什么涨", "为什么跌", "利好", "利空",
        "买入理由", "卖出理由",
        "该不该买", "该不该卖", "能不能买",
        "看多", "看空",  # 看多看空组合更偏决策
    ],
    ROLE_COMPETITOR: [
        "对比", "竞争", "同行", "行业地位", "市场份额",
        "vs", "VS", "比较", "竞品", "龙头",
        "相比", "优势", "劣势", "比怎么样", "哪个好",
    ],
}

# 市场筛选类关键词（用于识别是否为筛选意图，不参与角色路由）
SCREENING_KEYWORDS = [
    "筛选", "筛股", "筛一下", "选股", "排名", "排序",
    "最低", "最高", "前几", "前十", "前20", "前50", "TOP",
    "低估", "高估", "破净", "便宜的股票", "贵的股票",
    "哪些股票", "有哪些", "找一下", "帮我找",
    "全市场", "全A股", "A股中",
    "行业有哪些", "板块有哪些", "成分股",
]


def is_screening_intent(user_message: str) -> bool:
    """判断用户消息是否为全市场筛选意图。"""
    msg = user_message.lower()
    return any(kw.lower() in msg for kw in SCREENING_KEYWORDS)


def classify_intent(user_message: str, claude_client=None) -> str:
    """对用户消息进行意图分类，返回角色标识。

    1. 规则匹配（关键词）
    2. 如果命中多个角色且差异不大 → general
    3. 未命中 → LLM 分类（如果提供了 claude_client）
    4. 兜底 → general
    """
    msg = user_message.lower().strip()

    # 规则匹配：统计每个角色命中的关键词数
    scores: dict[str, int] = {}
    for role, keywords in INTENT_RULES.items():
        count = sum(1 for kw in keywords if kw.lower() in msg)
        if count > 0:
            scores[role] = count

    if scores:
        # 排序取最高分
        sorted_roles = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_role, top_score = sorted_roles[0]

        # 如果只命中一个角色 → 直接路由
        if len(sorted_roles) == 1:
            logger.info(f"意图路由(规则): {top_role} (score={top_score})")
            return top_role

        second_score = sorted_roles[1][1]

        # 最高分明显领先（>= 1.5 倍）→ 直接路由
        if top_score >= second_score * 1.5:
            logger.info(f"意图路由(规则): {top_role} (score={top_score} vs {second_score})")
            return top_role

        # 分数接近但只有 2 个角色命中 → 用得分最高的（不再 fallback general）
        if len(sorted_roles) == 2:
            logger.info(f"意图路由(择优): {top_role} (score={top_score} vs {second_score})")
            return top_role

        # 3 个及以上角色命中且分数接近 → general 综合回答
        logger.info(f"意图路由(多角色): general (scores={scores})")
        return ROLE_GENERAL

    # 未命中任何规则 → 尝试 LLM 分类
    if claude_client:
        return _llm_classify(msg, claude_client)

    logger.info("意图路由(兜底): general")
    return ROLE_GENERAL


def _llm_classify(message: str, claude_client) -> str:
    """用轻量模型做意图分类。"""
    try:
        prompt = (
            "你是一个投资研究系统的意图分类器。根据用户消息，判断应该由哪个专家回答。\n"
            "只回复角色标识，不要其他内容。\n\n"
            "可选角色：\n"
            "- financial: 财务/财报/估值相关\n"
            "- quant: 技术面/价格走势/指标相关\n"
            "- sentiment: 市场情绪/舆情/散户观点相关\n"
            "- debate: 看多看空/买卖决策/风险收益相关\n"
            "- competitor: 竞品对比/行业竞争相关\n"
            "- general: 综合问题/概览/其他\n\n"
            f"用户消息: {message}\n\n"
            "角色标识:"
        )
        result = claude_client.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
        )
        role = result.strip().lower()
        if role in INTENT_RULES or role == ROLE_GENERAL:
            logger.info(f"意图路由(LLM): {role}")
            return role
    except Exception as e:
        logger.warning(f"LLM 意图分类失败: {e}")

    logger.info("意图路由(LLM兜底): general")
    return ROLE_GENERAL


def get_role_name(role: str) -> str:
    """获取角色的中文名称。"""
    return ROLE_NAMES.get(role, "综合顾问")
