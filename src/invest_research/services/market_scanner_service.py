"""全市场筛选服务：基于 AKShare 全市场 API 实现 PE/PB/行业筛选。"""

import logging
import time

import akshare as ak
import pandas as pd

from invest_research.services.akshare_utils import call_akshare

logger = logging.getLogger(__name__)

# 缓存 TTL（秒）
CACHE_TTL = 3600  # 1 小时


class MarketScannerService:
    """全市场股票筛选，支持 PE/PB 排序、分位数过滤、行业成分查询。"""

    # 进程级缓存：(timestamp, DataFrame)
    _pe_cache: tuple[float, pd.DataFrame] | None = None
    _pb_cache: tuple[float, pd.DataFrame] | None = None
    _industry_cache: dict[str, tuple[float, pd.DataFrame]] = {}

    def _get_pe_data(self) -> pd.DataFrame:
        """获取全 A 股 PE 数据（带缓存）。"""
        now = time.time()
        if self._pe_cache and (now - self._pe_cache[0]) < CACHE_TTL:
            return self._pe_cache[1]

        logger.info("拉取全市场 PE 数据...")
        df = call_akshare(ak.stock_a_ttm_lyr, timeout=20, retries=2)
        MarketScannerService._pe_cache = (now, df)
        logger.info(f"PE 数据已缓存，共 {len(df)} 条")
        return df

    def _get_pb_data(self) -> pd.DataFrame:
        """获取全 A 股 PB 数据（带缓存）。"""
        now = time.time()
        if self._pb_cache and (now - self._pb_cache[0]) < CACHE_TTL:
            return self._pb_cache[1]

        logger.info("拉取全市场 PB 数据...")
        df = call_akshare(ak.stock_a_all_pb, timeout=20, retries=2)
        MarketScannerService._pb_cache = (now, df)
        logger.info(f"PB 数据已缓存，共 {len(df)} 条")
        return df

    def scan_by_pe(
        self,
        sort: str = "asc",
        limit: int = 50,
        percentile_min: float | None = None,
        percentile_max: float | None = None,
    ) -> dict:
        """按 PE 筛选全 A 股。

        Args:
            sort: "asc"=PE从低到高, "desc"=PE从高到低
            limit: 返回数量上限
            percentile_min/max: PE 历史分位数范围 (0-100)

        Returns:
            {"count": int, "total_scanned": int, "items": [{"code", "name", "pe", "pe_percentile"}, ...]}
        """
        df = self._get_pe_data()
        result = df.copy()

        # 分位数过滤
        pct_col = "quantileInAllHistoryMiddlePeTtm"
        if pct_col in result.columns:
            if percentile_min is not None:
                result = result[result[pct_col] >= percentile_min]
            if percentile_max is not None:
                result = result[result[pct_col] <= percentile_max]

        # 排序
        pe_col = "middlePETTM"
        if pe_col in result.columns:
            # 过滤无效值
            result = result[result[pe_col].notna() & (result[pe_col] > 0)]
            ascending = sort == "asc"
            result = result.sort_values(pe_col, ascending=ascending)

        total = len(result)
        result = result.head(limit)

        return self._format_pe_results(result, total)

    def scan_by_pb(
        self,
        sort: str = "asc",
        limit: int = 50,
        pb_min: float | None = None,
        pb_max: float | None = None,
        percentile_min: float | None = None,
        percentile_max: float | None = None,
    ) -> dict:
        """按 PB 筛选全 A 股。"""
        df = self._get_pb_data()
        result = df.copy()

        pb_col = "middlePB"
        pct_col = "quantileInAllHistoryMiddlePB"

        if pb_col in result.columns:
            result = result[result[pb_col].notna()]
            if pb_min is not None:
                result = result[result[pb_col] >= pb_min]
            if pb_max is not None:
                result = result[result[pb_col] <= pb_max]

        if pct_col in result.columns:
            if percentile_min is not None:
                result = result[result[pct_col] >= percentile_min]
            if percentile_max is not None:
                result = result[result[pct_col] <= percentile_max]

        if pb_col in result.columns:
            ascending = sort == "asc"
            result = result.sort_values(pb_col, ascending=ascending)

        total = len(result)
        result = result.head(limit)

        return self._format_pb_results(result, total)

    def scan_by_industry(self, industry_name: str, limit: int = 50) -> dict:
        """查询行业成分股。"""
        now = time.time()
        cached = self._industry_cache.get(industry_name)
        if cached and (now - cached[0]) < CACHE_TTL:
            df = cached[1]
        else:
            logger.info(f"拉取行业成分: {industry_name}")
            df = call_akshare(
                ak.stock_board_industry_cons_em,
                symbol=industry_name,
                timeout=15,
                retries=1,
            )
            MarketScannerService._industry_cache[industry_name] = (now, df)

        total = len(df)
        items = []
        for _, row in df.head(limit).iterrows():
            items.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "price": row.get("最新价"),
                "change_pct": row.get("涨跌幅"),
                "market_cap": row.get("总市值"),
                "pe": row.get("市盈率-动态"),
            })

        return {"count": len(items), "total_in_industry": total, "industry": industry_name, "items": items}

    def format_results_text(self, results: dict) -> str:
        """将筛选结果格式化为 Markdown 文本，注入 LLM 上下文。"""
        items = results.get("items", [])
        if not items:
            return "## 市场筛选结果\n\n未找到符合条件的股票。"

        lines = ["## 市场筛选结果"]

        # 统计信息
        total = results.get("total_matched", results.get("total_in_industry", results.get("total_scanned", 0)))
        count = results.get("count", len(items))
        industry = results.get("industry")

        if industry:
            lines.append(f"\n**{industry}行业** 共 {total} 只股票，展示前 {count} 只：")
        else:
            lines.append(f"\n共 {total} 只符合条件，展示前 {count} 只：")

        # 表格
        if industry:
            lines.append("\n| 代码 | 名称 | 现价 | 涨跌幅 | PE |")
            lines.append("|------|------|------|--------|-----|")
            for item in items:
                price = f"{item['price']:.2f}" if item.get("price") else "-"
                chg = f"{item['change_pct']:.2f}%" if item.get("change_pct") is not None else "-"
                pe = f"{item['pe']:.1f}" if item.get("pe") else "-"
                lines.append(f"| {item['code']} | {item['name']} | {price} | {chg} | {pe} |")
        elif "pe" in items[0]:
            lines.append("\n| 代码 | 名称 | PE(TTM) | PE历史分位 |")
            lines.append("|------|------|---------|-----------|")
            for item in items:
                pe = f"{item['pe']:.2f}" if item.get("pe") is not None else "-"
                pct = f"{item['pe_percentile']:.1f}%" if item.get("pe_percentile") is not None else "-"
                lines.append(f"| {item['code']} | {item['name']} | {pe} | {pct} |")
        elif "pb" in items[0]:
            lines.append("\n| 代码 | 名称 | PB | PB历史分位 |")
            lines.append("|------|------|-----|-----------|")
            for item in items:
                pb = f"{item['pb']:.2f}" if item.get("pb") is not None else "-"
                pct = f"{item['pb_percentile']:.1f}%" if item.get("pb_percentile") is not None else "-"
                lines.append(f"| {item['code']} | {item['name']} | {pb} | {pct} |")

        return "\n".join(lines)

    # === 内部格式化 ===

    def _format_pe_results(self, df: pd.DataFrame, total: int) -> dict:
        items = []
        for _, row in df.iterrows():
            items.append({
                "code": str(row.get("code", row.get("股票代码", ""))),
                "name": str(row.get("name", row.get("股票名称", ""))),
                "pe": row.get("middlePETTM"),
                "pe_percentile": row.get("quantileInAllHistoryMiddlePeTtm"),
            })
        return {"count": len(items), "total_matched": total, "items": items}

    def _format_pb_results(self, df: pd.DataFrame, total: int) -> dict:
        items = []
        for _, row in df.iterrows():
            items.append({
                "code": str(row.get("code", row.get("股票代码", ""))),
                "name": str(row.get("name", row.get("股票名称", ""))),
                "pb": row.get("middlePB"),
                "pb_percentile": row.get("quantileInAllHistoryMiddlePB"),
            })
        return {"count": len(items), "total_matched": total, "items": items}
