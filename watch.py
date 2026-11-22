import hashlib
import json
import re
import time
from email.utils import parsedate_to_datetime

from .memory import fish_id, official_rows
from .memory import key as entry_key

BASE = "https://api.yuyuworld.app/v1/"


class WatchError(ValueError):
    def __init__(self, status, retry=0):
        super().__init__(f"鱼世界观看接口 HTTP {status}")
        self.retry = retry


def valid_key(key):
    return isinstance(key, str) and bool(re.fullmatch(r"fwr_[^\s\x00-\x1f\x7f]{1,512}", key))


def retry_seconds(value):
    try:
        if value.isdigit():
            return min(86400, int(value))
        return min(86400, max(0, int(parsedate_to_datetime(value).timestamp() - time.time() + 1)))
    except (ValueError, TypeError, OverflowError):
        return 0


async def request(session, path, key, cursor=""):
    if path not in ("state", "notify") or not valid_key(key):
        raise ValueError("请先配置 fwr_ 观看密钥")
    async with session.get(
        BASE + path,
        headers={"Authorization": f"Bearer {key}"},
        params={"cursor": cursor} if cursor else None,
        allow_redirects=False,
    ) as response:
        if response.status != 200:
            raise WatchError(
                response.status, retry_seconds(response.headers.get("Retry-After", ""))
            )
        body = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body) > 512000:
                raise ValueError("观看响应过大")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("观看响应格式无效")
        return payload


async def identify(get):
    state = await get("state")
    own = fish_id(state.get("fish"))
    if not own:
        raise ValueError("观看状态缺少有效鱼编号")
    return own, state


async def sync(memory, key, get):
    own, state = await identify(get)
    if own != memory.fish:
        raise ValueError("观看密钥与当前绑定的鱼不一致")
    if state.get("stage") != "live":
        return "鱼尚未入住；未读取通知"
    _, previous = memory.load()
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    cursor = previous.get("cursor", "") if previous.get("key") == fingerprint else ""
    if not isinstance(cursor, str) or len(cursor) > 256:
        raise ValueError("以前的通知游标无效")
    notify = await get("notify", cursor)
    current = notify.get("cursor")
    items = notify.get("items")
    if (
        not isinstance(current, str)
        or not 0 < len(current) <= 256
        or not isinstance(items, list)
        or len(items) > 50
    ):
        raise ValueError("通知响应格式无效，已保留旧游标")
    batch = official_rows(state, notify if cursor else {"items": []})
    starting = next((row for row in batch if row["kind"] == "start"), None)
    signature = (
        json.dumps(entry_key(starting), ensure_ascii=False, separators=(",", ":"))
        if starting
        else ""
    )
    ignore = (
        previous.get("ignoreStart")
        if signature and signature == previous.get("ignoreStart")
        else ""
    )
    if ignore:
        batch.remove(starting)
    count = memory.merge(
        batch,
        {"key": fingerprint, "cursor": current, "lastStart": signature, "ignoreStart": ignore},
    )
    missed = notify.get("skipped")
    gap = f"；服务端略过 {missed} 条旧通知" if cursor and type(missed) is int and missed > 0 else ""
    return f"{'首次建立通知基准；' if not cursor else ''}本次新增 {count} 条{gap}"
