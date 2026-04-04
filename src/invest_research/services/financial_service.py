import logging

from invest_research.services.akshare_utils import call_akshare, AKShareError
from invest_research.services.market_utils import detect_market, normalize_stock_code

logger = logging.getLogger(__name__)

MAX_SUMMARY_LENGTH = 2000

# 需要展示的关键财务指标列（中英文映射）
KEY_INDICATORS = {
    # A 股
    "报告期": "报告期",
    "每股收益": "每股收益",
    "每股净资产": "每股净资产",
    "净资产收益率": "净资产收益率",
    "营业总收入": "营业总收入",
    "归母净利润": "归母净利润",
    "营业总收入同比增长率": "营收同比增长",
    "归母净利润同比增长率": "净利润同比增长",
    "毛利率": "毛利率",
    "净利率": "净利率",
    "资产负债率": "资产负债率",
    "流动比率": "流动比率",
    "速动比率": "速动比率",
    # 美股/港股（东方财富英文字段）
    "REPORT_DATE": "报告日期",
    "DATE_TYPE": "报告类型",
    "OPERATE_INCOME": "营业收入",
    "OPERATE_INCOME_YOY": "营收同比增长(%)",
    "GROSS_PROFIT": "毛利润",
    "GROSS_PROFIT_YOY": "毛利润同比增长(%)",
    "PARENT_HOLDER_NETPROFIT": "归母净利润",
    "PARENT_HOLDER_NETPROFIT_YOY": "净利润同比增长(%)",
    "BASIC_EPS": "基本每股收益",
    "DILUTED_EPS": "稀释每股收益",
    "GROSS_PROFIT_RATIO": "毛利率(%)",
    "NET_PROFIT_RATIO": "净利率(%)",
    "ROE_AVG": "净资产收益率ROE(%)",
    "ROA": "总资产收益率ROA(%)",
    "CURRENT_RATIO": "流动比率",
    "CURRENCY": "货币",
}

# A 股备用源（财报摘要）的关键指标
KEY_INDICATORS_ABSTRACT = {
    "报告日期": "报告期",
    "每股收益": "每股收益",
    "每股净资产": "每股净资产",
    "净资产收益率": "净资产收益率",
    "营业总收入": "营业总收入",
    "归属净利润": "归母净利润",
    "营业总收入同比增长": "营收同比增长",
    "归属净利润同比增长": "净利润同比增长",
    "毛利率": "毛利率",
    "净利率": "净利率",
    "负债率": "资产负债率",
}

# 内部字段，不展示给用户
EXCLUDE_COLUMNS = {
    "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE",
    "SECURITY_INNER_CODE", "ACCOUNTING_STANDARDS", "NOTICE_DATE",
    "START_DATE", "FINANCIAL_DATE", "STD_REPORT_DATE", "DATE_TYPE_CODE",
    "REPORT_TYPE", "REPORT_DATA_TYPE", "ORGTYPE",
}


class FinancialDataService:
    """通过 AKShare 获取公司财务指标数据并格式化为文本摘要。"""

    def fetch_summary(self, stock_code: str) -> str:
        if not stock_code:
            return ""

        primary_code = normalize_stock_code(stock_code)
        if not primary_code:
            return ""

        try:
            import akshare as ak

            market = detect_market(primary_code)
            if market == "A":
                return self._fetch_a_share(ak, primary_code)
            elif market == "US":
                return self._fetch_us_stock(ak, primary_code)
            elif market == "HK":
                return self._fetch_hk_stock(ak, primary_code)
            else:
                logger.warning("无法识别股票代码市场类型: %s", stock_code)
                return ""
        except AKShareError as e:
            logger.warning("获取财务数据失败 [%s]: %s", stock_code, e.message)
            return f"财报数据获取失败: {e.message}"
        except Exception as exc:
            logger.warning("获取财务数据失败 [%s]: %s", stock_code, exc, exc_info=True)
            return f"财报数据获取失败: {exc}"

    def _fetch_a_share(self, ak, stock_code: str) -> str:
        """A 股财报：主源 stock_financial_analysis_indicator_em，失败则切备用源。"""
        code = stock_code.split(".")[0]

        # 主数据源
        try:
            df = call_akshare(
                ak.stock_financial_analysis_indicator_em,
                symbol=code, indicator="按报告期",
                timeout=15, retries=1,
            )
            if df is not None and not df.empty:
                return self._format_dataframe(df.head(4), f"A股财务指标 ({stock_code})")
        except (AKShareError, TypeError) as e:
            logger.warning("A股主源获取失败 [%s]: %s，尝试备用源", stock_code, e)

        # 备用数据源：stock_financial_abstract（转置格式，更稳定）
        try:
            df = call_akshare(
                ak.stock_financial_abstract,
                symbol=code,
                timeout=15, retries=1,
            )
            if df is not None and not df.empty:
                logger.info("A股备用源获取成功 [%s]", stock_code)
                return self._format_abstract(df, f"A股财务摘要 ({stock_code})")
        except (AKShareError, TypeError) as e:
            logger.warning("A股备用源也失败 [%s]: %s", stock_code, e)

        return f"A股财报数据暂时无法获取（{stock_code}），数据源可能限制访问"

    def _fetch_us_stock(self, ak, stock_code: str) -> str:
        code = stock_code.split(".")[0]
        try:
            df = call_akshare(
                ak.stock_financial_us_analysis_indicator_em,
                symbol=code, indicator="单季报",
                timeout=15, retries=1,
            )
        except AKShareError as e:
            return f"美股财报数据获取失败（{stock_code}）: {e.message}"

        if df is None or df.empty:
            return f"未找到美股财报数据（{stock_code}）"
        return self._format_dataframe(df.head(4), f"美股财务指标 ({stock_code})")

    def _fetch_hk_stock(self, ak, stock_code: str) -> str:
        code = stock_code.split(".")[0]
        try:
            df = call_akshare(
                ak.stock_financial_hk_analysis_indicator_em,
                symbol=code, indicator="报告期",
                timeout=15, retries=1,
            )
        except AKShareError as e:
            return f"港股财报数据获取失败（{stock_code}）: {e.message}"

        if df is None or df.empty:
            return f"未找到港股财报数据（{stock_code}）"
        return self._format_dataframe(df.head(4), f"港股财务指标 ({stock_code})")

    # 备用源关注的指标行
    _ABSTRACT_INDICATORS = [
        "归母净利润", "营业总收入", "基本每股收益", "每股净资产",
        "净资产收益率(ROE)", "总资产报酬率(ROA)", "毛利率", "销售净利率",
        "资产负债率",
    ]

    @staticmethod
    def _format_abstract(df, title: str) -> str:
        """格式化转置格式的财报摘要（行=指标，列=日期）。"""
        # 取最近 4 个报告期列
        date_cols = [c for c in df.columns if c not in ("选项", "指标")]
        date_cols = date_cols[:4]

        lines = [title, "=" * len(title)]

        for col in date_cols:
            # 格式化日期 20250930 -> 2025-09-30
            d = col
            if len(d) == 8:
                d = f"{col[:4]}-{col[4:6]}-{col[6:]}"
            lines.append(f"\n📊 {d}")
            lines.append("-" * 30)

            seen = set()
            for _, row in df.iterrows():
                indicator = row.get("指标", "")
                if indicator not in FinancialDataService._ABSTRACT_INDICATORS:
                    continue
                if indicator in seen:
                    continue
                val = row.get(col)
                if val is None or str(val).strip() in ("", "nan", "None"):
                    continue
                seen.add(indicator)
                formatted_val = _format_value(indicator, val)
                lines.append(f"  {indicator}: {formatted_val}")

        summary = "\n".join(lines)
        if len(summary) > MAX_SUMMARY_LENGTH:
            summary = summary[:MAX_SUMMARY_LENGTH] + "\n..."
        return summary

    @staticmethod
    def _format_dataframe(df, title: str, key_indicators: dict | None = None) -> str:
        """将 DataFrame 格式化为结构化文本摘要。"""
        indicators = key_indicators or KEY_INDICATORS
        lines = [title, "=" * len(title)]

        for idx, (_, row) in enumerate(df.iterrows()):
            # 尝试确定报告期标题
            period_label = ""
            for col in ("报告期", "报告日期", "REPORT_DATE", "DATE_TYPE"):
                if col in df.columns:
                    val = row[col]
                    if val is not None and str(val).strip():
                        period_label = str(val).split(" ")[0]
                        break

            if period_label:
                lines.append(f"\n📊 {period_label}")
                lines.append("-" * 30)

            for col in df.columns:
                if col in EXCLUDE_COLUMNS:
                    continue

                val = row[col]
                if val is None or str(val).strip() == "":
                    continue

                display_name = indicators.get(col, col)
                formatted_val = _format_value(col, val)
                lines.append(f"  {display_name}: {formatted_val}")

            if idx < len(df) - 1:
                lines.append("")

        summary = "\n".join(lines)
        if len(summary) > MAX_SUMMARY_LENGTH:
            summary = summary[:MAX_SUMMARY_LENGTH] + "\n..."
        return summary


def _format_value(col: str, val) -> str:
    """格式化数值，大数字使用万/亿单位。"""
    if val is None:
        return ""

    str_val = str(val).strip()

    # 尝试格式化大数字（营收、利润等金额字段）
    amount_keywords = (
        "INCOME", "PROFIT", "营业", "净利", "毛利", "收入", "总资产",
    )
    is_amount_col = any(kw in col.upper() for kw in amount_keywords)

    if is_amount_col:
        try:
            num = float(str_val)
            if abs(num) >= 1e12:
                return f"{num / 1e12:.2f} 万亿"
            if abs(num) >= 1e8:
                return f"{num / 1e8:.2f} 亿"
            if abs(num) >= 1e4:
                return f"{num / 1e4:.2f} 万"
            return f"{num:,.2f}"
        except (ValueError, TypeError):
            pass

    # 百分比字段格式化
    pct_keywords = ("YOY", "RATIO", "ROE", "ROA", "率", "增长")
    is_pct_col = any(kw in col.upper() for kw in pct_keywords)
    if is_pct_col:
        try:
            num = float(str_val)
            return f"{num:.2f}%"
        except (ValueError, TypeError):
            pass

    return str_val
