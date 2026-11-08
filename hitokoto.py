# -*- coding: utf-8 -*-
"""一言 hitokoto（开发计划 P5）：面板一处小彩蛋。
每 24h 最多拉一次（缓存 data/hitokoto.json，留最近 5 条可点击轮换）；
拉取失败/离线 → 内置句库兜底。"""
import json
import os
import time
import logging
import datetime
import urllib.request
import random

log = logging.getLogger("hitokoto")

_BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(_BASE, "data", "hitokoto.json")
FETCH_INTERVAL = 24 * 3600

FALLBACK = [
    {"hitokoto": "想到就记，一句废话也行——找回来的时候你会感谢自己。", "from": "路远手册"},
    {"hitokoto": "山不让尘，川不辞盈。", "from": "张华《励志诗》"},
    {"hitokoto": "怕什么真理无穷，进一寸有一寸的欢喜。", "from": "胡适"},
    {"hitokoto": "日日行不怕千万里，常常做不怕千万事。", "from": "格言联璧"},
    {"hitokoto": "种一棵树最好的时间是十年前，其次是现在。", "from": "谚语"},
]


def _load_cache():
    try:
        with open(CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": [], "last_fetch": 0}


def _save_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception:
        pass


def _fetch_one():
    try:
        req = urllib.request.Request("https://v1.hitokoto.cn/?c=i&c=k&c=d",
                                     headers={"User-Agent": "luyuan/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        text = (d.get("hitokoto") or "").strip()
        if text:
            return {"hitokoto": text[:80], "from": (d.get("from") or "一言")[:30]}
    except Exception as e:
        log.info("hitokoto fetch failed: %s", e)
    return None


def current(force_fetch=False):
    """返回当前一言。默认 24h 最多拉一次；force_fetch=True（用户点击）立即真拉新，
    3 秒内连点不重复打 API（就地轮换缓存池）。"""
    c = _load_cache()
    items = c.get("items") or []
    now = time.time()
    if force_fetch or now - c.get("last_fetch", 0) >= FETCH_INTERVAL:
        if not (force_fetch and now - c.get("last_fetch", 0) < 3):
            fresh = _fetch_one()
            c["last_fetch"] = now
            if fresh:
                items = [i for i in items if i.get("hitokoto") != fresh["hitokoto"]]
                items.insert(0, fresh)
                items = items[:8]
            c["items"] = items or list(FALLBACK)
            _save_cache(c)
    pool = c.get("items") or list(FALLBACK)
    if not pool:
        pool = list(FALLBACK)
    idx = random.randrange(len(pool)) if (force_fetch and len(pool) > 1) else 0
    pick = dict(pool[idx])
    pick["pool_size"] = len(pool)
    pick["fetched_at"] = datetime.datetime.fromtimestamp(
        c.get("last_fetch", 0)).isoformat(timespec="minutes") if c.get("last_fetch") else ""
    return pick
