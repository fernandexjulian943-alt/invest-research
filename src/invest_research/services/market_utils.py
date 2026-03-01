"""共享的股票市场检测、代码标准化与名称搜索工具。"""

import logging
import re

logger = logging.getLogger(__name__)

# 进程级名称缓存: {market: [(code, name), ...]}
_name_cache: dict[str, list[tuple[str, str]]] = {}


def detect_market(stock_code: str) -> str:
    """根据股票代码格式判断市场类型。

    返回: 'A'（A股）, 'HK'（港股）, 'US'（美股）, 或 ''（无法识别）
    """
    code = stock_code.split(".")[0].strip()
    if re.match(r"^\d{6}$", code):
        return "A"
    if re.match(r"^\d{5}$", code):
        return "HK"
    if re.match(r"^[A-Za-z]+$", code):
        return "US"
    return ""


def normalize_stock_code(stock_code: str) -> str:
    """标准化股票代码。

    处理复合代码（如 'GOOGL/GOOG' 取第一个）、后缀（如 '000001.SZ' 去后缀）、
    港股短代码补零（如 '700' -> '00700'）。
    """
    primary = stock_code.split("/")[0].strip()
    code = primary.split(".")[0].strip()
    # 1-4 位纯数字视为港股，补零到 5 位
    if re.match(r"^\d{1,4}$", code):
        code = code.zfill(5)
    return code


def build_xq_symbol(stock_code: str, market: str) -> str:
    """构建雪球接口使用的 symbol 格式。

    A股: 6xx开头 -> 'SH600519', 0xx/3xx -> 'SZ000001'
    美股: 原样返回（如 'MSFT'）
    港股: 原样返回（如 '00700'）
    """
    if market == "A":
        if stock_code.startswith("6"):
            return f"SH{stock_code}"
        return f"SZ{stock_code}"
    return stock_code


def search_stock_by_name(keyword: str) -> tuple[str, str]:
    """通过名称关键词搜索股票代码。

    返回 (code, market)，未找到返回 ('', '')。
    使用进程级缓存，首次加载约 6 秒（A 股），后续即时返回。
    """
    keyword = keyword.strip()
    if not keyword:
        return ("", "")

    try:
        import akshare as ak

        # 1. A 股搜索（stock_info_a_code_name，~6s 首次，5000+ 只）
        if "A" not in _name_cache:
            _load_a_share_names(ak)
        for code, name in _name_cache.get("A", []):
            if keyword in name:
                return (code, "A")

        # 2. 美股热门搜索（stock_us_famous_spot_em，0.1s，~30 只）
        if "US_famous" not in _name_cache:
            _load_us_famous_names(ak)
        for code, name in _name_cache.get("US_famous", []):
            if keyword in name:
                return (code, "US")

        # 3. 港股热门搜索（stock_hk_famous_spot_em，0.15s，~100 只）
        if "HK_famous" not in _name_cache:
            _load_hk_famous_names(ak)
        for code, name in _name_cache.get("HK_famous", []):
            if keyword in name:
                return (code, "HK")

    except Exception:
        logger.warning("搜索股票名称失败: %s", keyword, exc_info=True)

    return ("", "")


def _load_a_share_names(ak) -> None:
    """加载 A 股代码-名称映射到缓存。"""
    try:
        df = ak.stock_info_a_code_name()
        _name_cache["A"] = [
            (str(row["code"]), str(row["name"]))
            for _, row in df.iterrows()
        ]
    except Exception:
        logger.warning("加载 A 股名称列表失败", exc_info=True)
        _name_cache["A"] = []


def _load_us_famous_names(ak) -> None:
    """加载美股热门股票名称到缓存。"""
    try:
        df = ak.stock_us_famous_spot_em()
        pairs = []
        for _, row in df.iterrows():
            raw_code = str(row.get("代码", ""))
            # 代码格式 "105.NVDA"，提取纯字母部分
            symbol = raw_code.split(".")[-1] if "." in raw_code else raw_code
            name = str(row.get("名称", ""))
            if symbol and name:
                pairs.append((symbol, name))
        _name_cache["US_famous"] = pairs
    except Exception:
        logger.warning("加载美股热门名称失败", exc_info=True)
        _name_cache["US_famous"] = []


def _load_hk_famous_names(ak) -> None:
    """加载港股热门股票名称到缓存。"""
    try:
        df = ak.stock_hk_famous_spot_em()
        pairs = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).zfill(5)
            name = str(row.get("名称", ""))
            if code and name:
                pairs.append((code, name))
        _name_cache["HK_famous"] = pairs
    except Exception:
        logger.warning("加载港股热门名称失败", exc_info=True)
        _name_cache["HK_famous"] = []
