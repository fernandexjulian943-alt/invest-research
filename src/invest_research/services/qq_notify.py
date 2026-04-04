"""QQ 主动消息通知模块，用于投研任务完成后推送结果。

配置从 /root/cc-remotework/projects.json 的 qq 字段读取，复用已有配置。
API 参考：QQ Bot 官方 HTTP API (https://bot.q.qq.com/wiki/develop/api-v2/)
"""

import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE = "https://api.sgroup.qq.com"
CONFIG_PATH = Path("/root/cc-remotework/projects.json")

# token 缓存
_cached_token: dict | None = None
# 主动消息序列号
_msg_seq: int = 0


def _load_qq_config() -> dict | None:
    """从 projects.json 读取 QQ 配置。"""
    try:
        data = json.loads(CONFIG_PATH.read_text())
        qq = data.get("qq")
        if not qq or not qq.get("appId") or not qq.get("clientSecret"):
            logger.warning("QQ 配置不完整，跳过通知")
            return None
        return qq
    except Exception as e:
        logger.error("读取 QQ 配置失败: %s", e)
        return None


def _get_access_token(app_id: str, client_secret: str) -> str:
    """获取 access_token，带缓存（提前 5 分钟刷新）。"""
    global _cached_token
    if _cached_token and time.time() < _cached_token["expires_at"] - 300:
        return _cached_token["token"]

    resp = httpx.post(TOKEN_URL, json={"appId": app_id, "clientSecret": client_secret}, timeout=10)
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取 QQ Token 失败: {data}")

    _cached_token = {
        "token": data["access_token"],
        "expires_at": time.time() + int(data.get("expires_in", 7200)),
    }
    logger.info("QQ Token 获取成功")
    return _cached_token["token"]


def notify(text: str) -> bool:
    """发送 QQ 主动消息通知。成功返回 True。"""
    global _msg_seq

    config = _load_qq_config()
    if not config:
        return False

    openid = config.get("notifyTarget")
    notify_type = config.get("notifyType", "c2c")
    if not openid:
        logger.warning("未配置 notifyTarget，跳过通知")
        return False

    try:
        token = _get_access_token(config["appId"], config["clientSecret"])

        _msg_seq += 1
        url = (
            f"{API_BASE}/v2/groups/{openid}/messages"
            if notify_type == "group"
            else f"{API_BASE}/v2/users/{openid}/messages"
        )
        body = {"content": text, "msg_type": 0, "msg_seq": _msg_seq}

        resp = httpx.post(
            url,
            json=body,
            headers={
                "Authorization": f"QQBot {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("QQ 通知发送失败 [%d]: %s", resp.status_code, resp.text)
            return False

        logger.info("QQ 通知已发送 (%s:%s...)", notify_type, openid[:8])
        return True
    except Exception as e:
        logger.error("QQ 通知发送异常: %s", e)
        return False
