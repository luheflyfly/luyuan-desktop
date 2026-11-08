"""课表域（`kind:"course"`，SYNC_FORMAT §10.1）。

这是"路远能不能替你安排时间"的地基，所以把三个历史坑写在最前面：

  1. **weekday 是 1..7（周一=1）**，跟 `datetime.isoweekday()` 同一套。
     用 `date.weekday()`（0=周一）去比对会**整体差一天**——周五看成周四。
  2. **周次是字符串，不是数字**："1-3,7-19" / "1,3,7,9" / "1-16(单)" 三种写法。
     `semester_start` 没配时旧代码一律当"每周都上"，会显示不该上的课（实测：第 7 周
     把第 8 周才开的化学实验也列出来）。
  3. **同名课可能有多条记录**（不同时段/不同周次），按 id 区分，别按名字去重。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from luyuan.core.store import JsonRepo

WEEKDAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}


def parse_weeks(weeks: str) -> tuple[set[int], str | None]:
    """'1-16' / '1-8,10-16' / '1-16(单)' → (周次集合, parity)。parity: None/'单'/'双'。"""
    weeks = str(weeks or "").strip()
    parity = None
    m = re.search(r"[（(](单|双)[)）]$", weeks)
    if m:
        parity = m.group(1)
        weeks = weeks[:m.start()]
    out: set[int] = set()
    for part in weeks.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            out.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out, parity


def week_in(weeks: str, week_no: int | None) -> bool:
    """本学年第 week_no 周是否上课。week_no 为 None（学期起点未配）→ 一律 True。"""
    if not week_no:
        return True
    wk, parity = parse_weeks(weeks)
    if wk and week_no not in wk:
        return False
    if parity == "单" and week_no % 2 == 0:
        return False
    if parity == "双" and week_no % 2 == 1:
        return False
    return True


def week_of(start: str | date | None, now: datetime | None = None) -> int | None:
    """学期第几周。start = 第一周的周一（'YYYY-MM-DD'）。"""
    if not start:
        return None
    if isinstance(start, str):
        try:
            start = date.fromisoformat(start.strip())
        except ValueError:
            return None
    now = now or datetime.now()
    days = (now.date() - start).days
    if days < 0:
        return None
    return days // 7 + 1


def _minutes(hm: str) -> int | None:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(hm or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _at(day: date, hm: str) -> datetime | None:
    mins = _minutes(hm)
    if mins is None:
        return None
    return datetime(day.year, day.month, day.day, mins // 60, mins % 60)


class CoursesRepo(JsonRepo):
    kind = "course"

    def __init__(self, directory=None, semester_start: str | None = None):
        super().__init__(directory)
        self.semester_start = semester_start

    # ── 基础 ───────────────────────────────────────────────
    def all_sorted(self) -> list[dict]:
        rows = self.visible()
        rows.sort(key=lambda c: (c.get("weekday") or 8, str(c.get("start") or "")))
        return rows

    def week(self, now: datetime | None = None) -> int | None:
        return week_of(self.semester_start, now)

    def in_week(self, now: datetime | None = None) -> list[dict]:
        """本周有效（按 weeks 过滤）的课。"""
        wk = self.week(now)
        return [c for c in self.all_sorted() if week_in(c.get("weeks"), wk)]

    # ── 今天 / 下一节 ──────────────────────────────────────
    def today(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        wd = now.isoweekday()          # ⚠️ 1=周一，和课程数据的 weekday 同一套
        wk = self.week(now)
        rows = [c for c in self.all_sorted()
                if c.get("weekday") == wd and week_in(c.get("weeks"), wk)]
        rows.sort(key=lambda c: str(c.get("start") or ""))
        return rows

    def next_class(self, now: datetime | None = None, lookahead_days: int = 8) -> dict | None:
        """下一节课（含倒计时分钟）。今天没了看明天，最多往后找 lookahead_days 天。"""
        now = now or datetime.now()
        wk = self.week(now)
        for offset in range(lookahead_days):
            day = now.date() + timedelta(days=offset)
            wd = day.isoweekday()
            rows = [c for c in self.all_sorted()
                    if c.get("weekday") == wd and week_in(c.get("weeks"), wk)]
            rows.sort(key=lambda c: str(c.get("start") or ""))
            for c in rows:
                dt = _at(day, c.get("start"))
                if dt is None:
                    continue
                if offset == 0 and dt <= now:
                    continue
                return {"course": c, "at": dt.isoformat(timespec="minutes"),
                        "minutes_away": int((dt - now).total_seconds() // 60)}
        return None

    def due_soon(self, window_minutes: int = 15, now: datetime | None = None) -> list[dict]:
        """即将上课（距 start ∈ (0, window] 分钟）——课前提醒就靠它。"""
        now = now or datetime.now()
        out = []
        for c in self.today(now):
            dt = _at(now.date(), c.get("start"))
            if dt is None:
                continue
            mins = (dt - now).total_seconds() / 60
            if 0 < mins <= window_minutes:
                out.append({"course": c, "minutes_away": int(mins + 0.999)})
        return out

    # ── 给界面用的一句话 ───────────────────────────────────
    @staticmethod
    def describe(c: dict) -> str:
        wd = WEEKDAY_CN.get(c.get("weekday") or 0, "")
        place = c.get("place") or "教室没填"
        return f"{wd} {c.get('start','')}-{c.get('end','')} {c.get('name','')} @ {place}"

    def brief_next(self, now: datetime | None = None) -> str | None:
        """「下一节 高等数学A（一）@潇湘校区-B座212 · 周一 08:00」这种人话。"""
        nx = self.next_class(now)
        if not nx:
            return None
        c = nx["course"]
        at = datetime.fromisoformat(nx["at"])
        mins = nx["minutes_away"]
        when = "今天" if at.date() == (now or datetime.now()).date() else f"{WEEKDAY_CN.get(at.isoweekday(),'')}"
        if mins < 60:
            tail = f"还有 {mins} 分钟"
        elif mins < 60 * 24:
            tail = f"还有 {mins // 60} 小时"
        else:
            tail = f"还有 {mins // 1440} 天"
        return f"下一节 {c.get('name','')} @{c.get('place') or '教室没填'} · {when} {c.get('start','')}（{tail}）"


_repo: CoursesRepo | None = None


def repo() -> CoursesRepo:
    """按当前配置里的 semester_start 构造/复用。配置改了就重建（周次立刻生效）。"""
    global _repo
    from luyuan.config import Config
    start = str(Config.load().get("semester_start") or "")
    if _repo is None or _repo.semester_start != start:
        _repo = CoursesRepo(semester_start=start)
    return _repo
