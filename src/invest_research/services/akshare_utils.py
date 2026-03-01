"""AKShare 调用统一包装：超时控制、重试、友好错误。"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import wraps

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="akshare")

AKSHARE_TIMEOUT = 10  # 秒
AKSHARE_RETRIES = 1


class AKShareError(Exception):
    """AKShare 调用失败的统一异常。"""

    def __init__(self, message: str, error_code: str = "SERVICE_ERROR", suggestion: str = ""):
        self.message = message
        self.error_code = error_code
        self.suggestion = suggestion or "请稍后重试，或检查股票代码是否正确"
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": self.message,
            "error_code": self.error_code,
            "suggestion": self.suggestion,
        }


def call_akshare(func, *args, timeout: int = AKSHARE_TIMEOUT, retries: int = AKSHARE_RETRIES, **kwargs):
    """调用 AKShare 函数，带超时和重试。

    Args:
        func: AKShare 函数（如 ak.stock_history_dividend_detail）
        timeout: 超时秒数
        retries: 重试次数（0 = 不重试）

    Returns:
        AKShare 函数的返回值（通常是 DataFrame）

    Raises:
        AKShareError: 调用失败时抛出，含友好错误信息
    """
    last_error = None
    for attempt in range(1 + retries):
        try:
            future = _executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            last_error = AKShareError(
                f"数据获取超时（{timeout}秒），接口: {func.__name__}",
                error_code="TIMEOUT",
                suggestion="数据源响应缓慢，请稍后重试",
            )
            logger.warning("AKShare 超时 [%s] 第 %d 次", func.__name__, attempt + 1)
        except TypeError as e:
            # AKShare 接口参数变更
            raise AKShareError(
                f"接口参数错误: {e}",
                error_code="API_CHANGED",
                suggestion="数据源接口可能已更新，请联系管理员",
            ) from e
        except KeyError as e:
            raise AKShareError(
                f"数据字段缺失: {e}",
                error_code="DATA_ERROR",
                suggestion="数据源返回格式可能已变更",
            ) from e
        except Exception as e:
            error_msg = str(e)
            if "不存在" in error_msg or "not found" in error_msg.lower():
                raise AKShareError(
                    f"未找到该股票数据: {error_msg}",
                    error_code="NOT_FOUND",
                    suggestion="请检查股票代码是否正确",
                ) from e
            last_error = AKShareError(
                f"数据获取失败: {error_msg}",
                error_code="SERVICE_ERROR",
            )
            logger.warning("AKShare 错误 [%s] 第 %d 次: %s", func.__name__, attempt + 1, e)

    raise last_error


def safe_api_response(func):
    """装饰器：捕获 AKShareError 并返回统一错误格式。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AKShareError as e:
            logger.warning("API 错误 [%s]: %s", func.__name__, e.message)
            return e.to_dict()

    return wrapper
