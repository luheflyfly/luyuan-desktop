"""提醒：路远主动开口的**唯一出口**。

设计要点（正面回应"通知太多、一眼看过去没作用"）：
  1. **一条提醒只为一件事**，且必须带"什么时候 + 什么 + 要你做什么"。
  2. **同一天同一件事只说一次**（去重键），说了没人看也不会复读。
  3. **没有内容就不发**（`text` 为空直接丢弃，不写"暂无"）。
  4. 每条留下 `reason`（为什么现在说），将来面板上要能解释"它为什么烦我"。

当前触达方式：落 `data/state/reminders.jsonl` + 内存队列，由 `/api/reminders` 读；
系统通知/手机推送在 io 层接（P4）。`dry_run` 时连文件都不写，只进内存。
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from luyuan import paths
from luyuan.core import courses as courses_repo
from luyuan.io import weather as wx
from luyuan.logs import get

log = get("jobs.reminders")

MAX_KEEP = 200


class ReminderBus:
    """提醒队列：去重 + 有界 + 可回看。"""

    def __init__(self, path: Path | None = None, dry_run: bool = True):
        self.path = path or paths.state_file("reminders.jsonl")
        self.dry_run = dry_run
        self._items: list[dict] = []
        self._seen: set[str] = set()
        self._load()

    # ── 持久化 ─────────────────────────────────────────────
    def _load(self) -> None:
        if self.dry_run or not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines()[-MAX_KEEP:]:
                if line.strip():
                    self._items.append(json.loads(line))
            self._seen = {i.get("key", "") for i in self._items if i.get("key")}
        except Exception as e:  # noqa: BLE001
            log.warning("提醒历史读取失败：%s", e)

    def _append(self, item: dict) -> None:
        if self.dry_run:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("提醒写入失败：%s", e)

    # ── 入队 ───────────────────────────────────────────────
    def push(self, kind: str, text: str, key: str = "", reason: str = "",
             meta: dict | None = None) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None                      # 没内容不发
        if key and key in self._seen:
            return None                      # 同一天同一件事只说一次
        item = {
            "id": str(uuid.uuid4())[:8],
            "kind": kind,
            "text": text,
            "reason": reason,
            "key": key,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ts": time.time(),
            "meta": meta or {},
            "read": False,
        }
        self._items.append(item)
        if len(self._items) > MAX_KEEP:
            self._items = self._items[-MAX_KEEP:]
        if key:
            self._seen.add(key)
        self._append(item)
        log.info("提醒[%s] %s", kind, text)
        return item

    # ── 出队 ───────────────────────────────────────────────
    def pending(self) -> list[dict]:
        return [i for i in self._items if not i.get("read")]

    def recent(self, limit: int = 50) -> list[dict]:
        return self._items[-limit:][::-1]

    def ack(self, rid: str) -> bool:
        for i in self._items:
            if i.get("id") == rid:
                i["read"] = True
                return True
        return False

    def ack_all(self) -> int:
        n = 0
        for i in self._items:
            if not i.get("read"):
                i["read"] = True
                n += 1
        return n


# ── 具体任务 ────────────────────────────────────────────────
def make_class_soon_job(bus: ReminderBus, window: int = 15, now_fn=None):
    """课前提醒：距上课 ∈ (0, window] 分钟时说一句。每个课次一天只说一次。

    `now_fn` 只给测试用（注入"假装现在是周一 7:50"），生产不传。
    """
    now_fn = now_fn or datetime.now

    def run() -> str:
        now = now_fn()
        repo = courses_repo.repo()
        items = repo.due_soon(window_minutes=window, now=now)
        if not items:
            return ""
        said = []
        today = now.strftime("%Y-%m-%d")
        for it in items:
            c = it["course"]
            key = f"class:{c.get('id')}:{today}"
            text = (f"{c.get('start','')} 有课：{c.get('name','')}"
                    f" @{c.get('place') or '教室没填'}"
                    f"，还有 {it['minutes_away']} 分钟")
            if bus.push("class_soon", text, key=key,
                        reason=f"{window} 分钟内要上课",
                        meta={"course_id": c.get("id")}):
                said.append(text)
        return "；".join(said)

    return run


def make_weather_job(bus: ReminderBus, city: str = "长沙市",
                     morning_hours: tuple[int, int] = (6, 10)):
    """天气提醒：每天早上说一次（只在 6–10 点之间），说"带不带伞/穿多少"。"""

    def run() -> str:
        now = datetime.now()
        if not (morning_hours[0] <= now.hour < morning_hours[1]):
            return ""
        w = wx.fetch(city)
        if not w:
            return ""
        key = f"weather:{now.strftime('%Y-%m-%d')}"
        said = bus.push("weather", w.brief(), key=key,
                        reason="每天早上一次天气",
                        meta={"city": w.place.name, "pop": w.pop})
        return w.brief() if said else ""

    return run


def make_week_job(bus: ReminderBus):
    """周一开场：第几周、本周几门课。只在一周开始时说，避免天天报。"""

    def run() -> str:
        now = datetime.now()
        if now.isoweekday() != 1 or now.hour > 12:
            return ""
        repo = courses_repo.repo()
        wk = repo.week(now)
        if not wk:
            return ""
        rows = repo.in_week(now)
        key = f"week:{now.strftime('%Y-%m-%d')}"
        text = f"第 {wk} 周，本周 {len(rows)} 门课。{repo.brief_next(now) or ''}".strip()
        said = bus.push("week_start", text, key=key, reason="周一开场")
        return text if said else ""

    return run
