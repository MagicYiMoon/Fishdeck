from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
FORMAT = "fishdeck-v1"
CAP = 2000
MAX_BYTES = 12_000_000
KINDS = {"arrive", "start", "done", "agreement"}
SOURCES = {"watch", "journal-copy", "fish-note"}
FISH = re.compile(r"#[0-9]{1,16}$")
SECRET = re.compile(r"(?:fwr?_[\w./+=-]+|sk-[\w-]{12,}|\bBearer\s+|https?://|\[CQ:)", re.I)
UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
PRIVATE = re.compile(
    r"私信|留言原文|当面对.+说|给.+发消息|门牌|密码|密钥|[0-9]+栋|[0-9]+单元|[0-9]+[室户]"
)
JOURNAL = re.compile(r"^(?:[-*]\s*)?((?:[01][0-9]|2[0-3]):[0-5][0-9])(?:\s+|$)(.*)$")
JOURNAL_PREFIX = re.compile(r"^(开始|完成|结束|抵达|到达)[：:]\s*(.+)$|^(到了.+)$")


def fish_id(value):
    match = FISH.search(value.strip()) if isinstance(value, str) else None
    return match[0] if match else ""


def require_fish(value):
    if not isinstance(value, str) or not FISH.fullmatch(value):
        raise ValueError("请使用官方鱼编号，例如 #123")
    return value


def clean(value, limit):
    if not isinstance(value, str) or UNSAFE.search(value) or SECRET.search(value):
        return ""
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if PRIVATE.search(value) or SECRET.search(value) or len(value) > limit:
        return ""
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", value):
        raise ValueError("日期请填 YYYY-MM-DD（北京时间）")
    return date.fromisoformat(value).isoformat()


def minute(value):
    if type(value) is not int or not 946684800000 <= value < 4102444800000:
        raise ValueError("事件时间无效")
    return value // 60000 * 60000


def row(time, kind, text, source, place="", people=None):
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("事件类别无效")
    if not isinstance(source, str) or source not in SOURCES:
        raise ValueError("事件来源无效")
    is_agreement = kind == "agreement"
    if is_agreement != (source == "fish-note"):
        raise ValueError("约定必须标记为鱼自主记录")
    text = clean(text, 160 if is_agreement else 260)
    if not text:
        raise ValueError("事件摘要超长、为空或含敏感内容")
    companions = []
    if is_agreement:
        if not isinstance(people, list) or len(people) != 1:
            raise ValueError("约定必须有一个对方鱼编号")
        companions = [require_fish(people[0])]
    elif isinstance(people, list):
        for member in people[:20]:
            name = clean(member, 40)
            if fish_id(name) and name not in companions:
                companions.append(name)
    return {
        "time": minute(time),
        "kind": kind,
        "text": text,
        "source": source,
        **({"place": value} if (value := clean(place, 90)) else {}),
        **({"people": companions} if companions else {}),
    }


def official_rows(state, notify):
    rows = []
    for item in notify["items"]:
        if not isinstance(item, dict) or item.get("kind") not in ("arrive", "done"):
            continue
        try:
            rows.append(row(item.get("t"), item["kind"], item.get("text"), "watch"))
        except ValueError:
            continue
    doing = state.get("doing")
    if isinstance(doing, dict) and isinstance(doing.get("since"), str):
        try:
            when = datetime.fromisoformat(doing["since"].replace("Z", "+00:00"))
            if when.tzinfo is not None:
                where = state.get("where")
                place = where.get("place") if isinstance(where, dict) else None
                rows.append(
                    row(
                        int(when.timestamp() * 1000),
                        "start",
                        doing.get("name"),
                        "watch",
                        place.get("name") if isinstance(place, dict) else "",
                        doing.get("with"),
                    )
                )
        except (ValueError, OverflowError):
            pass
    return rows


def diary_rows(content, on_day):
    on_day = day(on_day)
    if not isinstance(content, str) or len(content.encode("utf-8")) > 250_000:
        raise ValueError("日记文件过大")
    rows = []
    waiting = ""
    for line in content.splitlines():
        line = line.strip()
        tagged = JOURNAL.match(line)
        if tagged:
            waiting, line = tagged.groups()
            if not line:
                continue
        slot, waiting = waiting, ""
        if not slot:
            continue
        tagged = JOURNAL_PREFIX.fullmatch(line)
        if not tagged:
            continue
        prefix, text, arrived = tagged.groups()
        kind = (
            "start"
            if prefix == "开始"
            else "arrive"
            if prefix in ("抵达", "到达") or arrived
            else "done"
        )
        stamp = int(datetime.fromisoformat(f"{on_day}T{slot}:00+08:00").timestamp() * 1000)
        try:
            rows.append(row(stamp, kind, arrived or text, "journal-copy"))
        except ValueError:
            continue
    return rows


def verified_rows(bundle, fish):
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT or bundle.get("fish") != fish:
        raise ValueError("记忆文件格式不兼容或鱼编号不一致")
    entries = bundle.get("entries")
    if not isinstance(entries, list) or len(entries) > CAP:
        raise ValueError("记忆文件条数无效")
    result = []
    for item in entries:
        if not isinstance(item, dict) or set(item) - {
            "time",
            "kind",
            "text",
            "source",
            "place",
            "people",
        }:
            raise ValueError("记忆条目格式无效")
        entry = row(
            item.get("time"),
            item.get("kind"),
            item.get("text"),
            item.get("source"),
            item.get("place", ""),
            item.get("people"),
        )
        if entry["kind"] == "agreement" and entry["people"][0] == fish:
            raise ValueError("约定的对方不能是自己")
        result.append(entry)
    return result


def read_json(path):
    with path.open("rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError("记忆文件不是普通文件")
        content = f.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("记忆文件体积超出限制")
    return json.loads(content.decode("utf-8-sig"))


def atomic_json(path, value):
    data = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("记忆库体积超出限制")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def key(item):
    who = item["text"]
    if item["kind"] == "agreement":
        return "agreement", item["people"][0], who.lower()
    match = re.match(r"^到了\s*(.+)$", who) if item["kind"] == "arrive" else None
    return item["time"], item["kind"], (match[1] if match else who).lower()


class Memory:
    def __init__(self, root, fish):
        self.fish = require_fish(fish)
        self.path = Path(root) / f"{fish[1:]}.json"

    def load(self):
        try:
            stored = read_json(self.path)
        except FileNotFoundError:
            return [], {}
        rows = verified_rows(stored, self.fish)
        watch = stored.get("watch", {})
        if not isinstance(watch, dict):
            raise ValueError("本地同步记录损坏")
        return rows, watch

    def write(self, entries, watch):
        atomic_json(self.path, {**self.bundle(entries), "watch": watch})

    def bundle(self, entries):
        return {"format": FORMAT, "fish": self.fish, "entries": entries}

    def merge(self, batch, watch=None):
        existing, before = self.load()
        entries = {key(item): item for item in existing}
        for item in batch:
            fingerprint = key(item)
            previous = entries.get(fingerprint)
            if not previous or (item["source"] == "watch" and previous["source"] != "watch"):
                entries[fingerprint] = item
            elif item["source"] == previous["source"]:
                enriched = {**item, **previous}
                people = list(dict.fromkeys(previous.get("people", []) + item.get("people", [])))[
                    :20
                ]
                if people:
                    enriched["people"] = people
                entries[fingerprint] = enriched
        kept = sorted(entries.values(), key=lambda v: v["time"], reverse=True)[:CAP]
        added = len({key(v) for v in kept} - {key(v) for v in existing})
        if kept != existing or (watch is not None and watch != before):
            self.write(kept, before if watch is None else watch)
        return added

    def remember_agreement(self, peer, summary):
        peer = require_fish(peer)
        if peer == self.fish:
            raise ValueError("约定的对方不能是自己")
        timestamp = int(datetime.now(TZ).timestamp() * 1000)
        return self.merge([row(timestamp, "agreement", summary, "fish-note", people=[peer])])

    def export(self, path):
        rows, _ = self.load()
        atomic_json(path, self.bundle(rows))
        return len(rows)

    def import_file(self, path):
        return self.merge(verified_rows(read_json(path), self.fish))

    def clear(self):
        rows, watch = self.load()
        self.write([], {**watch, "ignoreStart": watch.get("lastStart", "")})
        return len(rows)

    def search(self, query="", on_day="", kind="", limit=8):
        if not isinstance(query, str) or len(query) > 100 or (query and not clean(query, 100)):
            raise ValueError("关键词无效")
        if not isinstance(kind, str) or kind and kind not in KINDS:
            raise ValueError("类别应为 arrive、start、done 或 agreement")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("条数应为 1–20")
        on_day = day(on_day) if on_day != "" else ""
        terms = clean(query, 100).lower().split()
        rows, _ = self.load()
        matches = []
        for item in rows:
            stamp = datetime.fromtimestamp(item["time"] / 1000, TZ)
            haystack = " ".join(
                [item["text"], item.get("place", ""), *item.get("people", [])]
            ).lower()
            if (
                (not on_day or stamp.date().isoformat() == on_day)
                and (not kind or kind == item["kind"])
                and all(
                    term == item["people"][0]
                    if item["kind"] == "agreement" and FISH.fullmatch(term)
                    else term in haystack
                    for term in terms
                )
            ):
                matches.append({**item, "beijing": stamp.strftime("%Y-%m-%d %H:%M")})
            if len(matches) == limit:
                break
        return matches
