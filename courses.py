# -*- coding: utf-8 -*-
"""课程存储（SYNC_FORMAT v2 §10.1）：kind:"course" 一节一门课，落 data/notes/。
时间轴关联器：自动归课（笔记时间 ±15 分钟落进某课时段）、下节课、课前提醒。"""
import os
import re
import uuid
import datetime
import threading

_BASE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(_BASE, "data", "notes")
_LOCK = threading.Lock()

WEEKDAY_NAMES = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _write(fp, c):
    import json
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def _read(fp):
    import json
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _all_files():
    import glob
    return sorted(f for f in glob.glob(os.path.join(_DIR, "course_*.json"))
                  if ".sync-conflict" not in os.path.basename(f))


def _valid_weekday(d):
    return isinstance(d, int) and 1 <= d <= 7


def add(name, teacher="", place="", weekday=1, start="", end="",
        weeks="1-16", semester="", cat=""):
    """新增课程。weekday 1=周一…7=周日；start/end 'HH:MM'；cat=课程分类（木案课表）。"""
    name = (name or "").strip()
    if not name or not _valid_weekday(weekday):
        return None
    try:
        weekday = int(weekday)
    except (TypeError, ValueError):
        return None
    c = {
        "kind": "course", "id": str(uuid.uuid4()), "schema": 2, "device": "pc",
        "deleted": False,
        "name": name[:40], "teacher": (teacher or "").strip()[:20],
        "place": (place or "").strip()[:40],
        "weekday": weekday,
        "start": _hm(start) or "08:00", "end": _hm(end) or "09:40",
        "weeks": (str(weeks) or "1-16").strip() or "1-16",
        "cat": (cat or "").strip()[:12],
        "semester": (semester or "").strip()[:30],
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    with _LOCK:
        _write(os.path.join(_DIR, "course_%s.json" % c["id"][:8]), c)
    return c


def _hm(s):
    """归一成 HH:MM；解析不出返回 None。"""
    m = re.match(r"^(\d{1,2})[:：.](\d{2})$", str(s or "").strip())
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return "%02d:%02d" % (hh, mm)
    return None


def list_courses():
    out = []
    for fp in _all_files():
        c = _read(fp)
        if c and not c.get("deleted"):
            out.append(c)
    out.sort(key=lambda c: (c.get("weekday", 8), c.get("start", "")))
    return out


def update(cid, fields):
    with _LOCK:
        for fp in _all_files():
            c = _read(fp)
            if c and c.get("id") == cid:
                for k in ("name", "teacher", "place", "weeks", "semester", "cat"):
                    if k in (fields or {}):
                        c[k] = str(fields[k]).strip()[:40]
                if "weekday" in (fields or {}) and _valid_weekday(fields["weekday"]):
                    c["weekday"] = int(fields["weekday"])
                for k in ("start", "end"):
                    if k in (fields or {}) and _hm(fields[k]):
                        c[k] = _hm(fields[k])
                c["updated_at"] = _now_iso()
                _write(fp, c)
                return c
    return None


def delete(cid):
    with _LOCK:
        for fp in _all_files():
            c = _read(fp)
            if c and c.get("id") == cid:
                try:
                    os.remove(fp)
                    return True
                except OSError:
                    return False
    return False


def _parse_weeks(weeks):
    """'1-16' / '1-8,10-16' / '1-16(单)' → (周次集合, parity)。parity: None/'单'/'双'。"""
    weeks = str(weeks or "").strip()
    parity = None
    m = re.search(r"[（(](单|双)[)）]$", weeks)
    if m:
        parity = m.group(1)
        weeks = weeks[:m.start()]
    out = set()
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


def week_in(weeks, week_no):
    """本学年第 week_no 周是否上课。week_no None（学期起点未配）→ 一律 True。"""
    if not week_no:
        return True
    wk, parity = _parse_weeks(weeks)
    if wk and week_no not in wk:
        return False
    if parity == "单" and week_no % 2 == 0:
        return False
    if parity == "双" and week_no % 2 == 1:
        return False
    return True


def current_week(now=None):
    """当前教学周号。需要 config.semester_start（'YYYY-MM-DD'，第一周周一）。
    未配置返回 None（=不过滤周次）。"""
    import config as _cfg
    start = (_cfg.load().get("semester_start") or "").strip()
    if not start:
        return None
    try:
        d0 = datetime.datetime.fromisoformat(start).date()
    except ValueError:
        return None
    now = now or datetime.datetime.now()
    days = (now.date() - d0).days
    if days < 0:
        return None
    return days // 7 + 1


def _minutes(hm):
    hh, mm = hm.split(":")
    return int(hh) * 60 + int(mm)


def today_courses(now=None):
    """今天（按周次过滤后）的课，按开始时间排序。"""
    now = now or datetime.datetime.now()
    wd = now.isoweekday()
    wk = current_week(now)
    out = [c for c in list_courses()
           if c.get("weekday") == wd and week_in(c.get("weeks"), wk)]
    out.sort(key=lambda c: c.get("start", ""))
    return out


def next_class(now=None):
    """下一节课（含倒计时分钟）。今天没了看明天（最多往后找 7 天）。"""
    now = now or datetime.datetime.now()
    wk = current_week(now)
    for offset in range(8):
        day = now + datetime.timedelta(days=offset)
        wd = day.isoweekday()
        day_courses = [c for c in list_courses()
                       if c.get("weekday") == wd and week_in(c.get("weeks"), wk)]
        day_courses.sort(key=lambda c: c.get("start", ""))
        for c in day_courses:
            st = _hm(c.get("start"))
            if not st:
                continue
            dt = day.replace(hour=int(st[:2]), minute=int(st[3:]),
                             second=0, microsecond=0)
            if offset == 0 and dt <= now:
                continue
            return {"course": c, "at": dt.isoformat(timespec="minutes"),
                    "minutes_away": int((dt - now).total_seconds() // 60)}
    return None


def due_soon(window_minutes=15, now=None):
    """即将上课（距 start ∈ (0, window] 分钟）的课，供课前提醒。"""
    now = now or datetime.datetime.now()
    out = []
    for c in today_courses(now):
        st = _hm(c.get("start"))
        if not st:
            continue
        dt = now.replace(hour=int(st[:2]), minute=int(st[3:]), second=0, microsecond=0)
        mins = (dt - now).total_seconds() / 60
        if 0 < mins <= window_minutes:
            out.append({"course": c, "minutes_away": int(mins // 1) + (1 if mins % 1 else 0)})
    return out


def auto_tag_courses(created_at, now=None):
    """笔记创建时间落在某课时段 ±15 分钟 → 返回应打的课程名 tag 列表。"""
    try:
        t = datetime.datetime.fromisoformat(str(created_at))
    except (ValueError, TypeError):
        return []
    if t.tzinfo is None:
        t = t.astimezone()
    out = []
    for c in today_courses(t):
        st, en = _hm(c.get("start")), _hm(c.get("end"))
        if not st or not en:
            continue
        base = t.replace(hour=0, minute=0, second=0, microsecond=0)
        sdt = base + datetime.timedelta(minutes=_minutes(st) - 15)
        edt = base + datetime.timedelta(minutes=_minutes(en) + 15)
        if sdt <= t <= edt:
            out.append(c.get("name", ""))
    return [n for n in out if n]


def bulk(items):
    """批量导入（木案课表解析结果）。items: list of dict（add 的参数名）。
    去重：同 weekday+start+name 已存在则跳过。返回 (added, skipped)。"""
    added = skipped = 0
    existing = {(c.get("weekday"), c.get("start"), c.get("name"))
                for c in list_courses()}
    for it in items or []:
        try:
            key = (int(it.get("weekday", 0)), _hm(it.get("start")) or "08:00",
                   (it.get("name") or "").strip()[:40])
        except (TypeError, ValueError):
            skipped += 1
            continue
        if key in existing:
            skipped += 1
            continue
        c = add(name=it.get("name"), teacher=it.get("teacher", ""),
                place=it.get("place", ""), weekday=it.get("weekday", 1),
                start=it.get("start", ""), end=it.get("end", ""),
                weeks=it.get("weeks", "1-16"), cat=it.get("cat", ""))
        if c:
            existing.add(key)
            added += 1
        else:
            skipped += 1
    return added, skipped
