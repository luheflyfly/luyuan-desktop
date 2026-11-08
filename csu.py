# -*- coding: utf-8 -*-
"""CSU 学业助手（2026-09-14 自提案一·统筹批复主菜）：校历事件进提醒库 + 综测/奖学金/竞赛速查。

数据源：data/csu_luyuan_data.json（路河 09-14 凌晨整理，7 院样本；个人数字标
「待核实」，见 pending_verification）。口径拍板：锚点=新生，2026-09-14 为
2026-2027 学年第一学期第一周周一。

三个入口（server.py 暴露）：
  week_info()               今天是第几周（新生锚点）+ 学期信息
  upcoming(days)            未来 N 天校历事件（含进行中的区间事件）
  import_calendar(days=120) 未来事件 → 提醒库（幂等；text=[校历] 开头，remind_at=当天 08:00）
  quick(q)                  奖学金/竞赛/综测加分/推免 统一速查（关键词过滤）
  seed_notes()              三条速查汇总笔记（问路远可检索；幂等）
  pending()                 待核实清单（个人数字不阻塞，但如实展示）

⚠️ 写提醒库走 store.add_note（source="csu"），绝不碰真实笔记的读取口径之外的字段；
   测试一律 notes_dir 指临时目录。
"""
import json
import os
import re
import time
import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_BASE, "data", "csu_luyuan_data.json")
import logging
log = logging.getLogger("csu")

_CACHE = {"d": None, "ts": 0.0}


def _load():
    now = time.time()
    if _CACHE["d"] is not None and now - _CACHE["ts"] < 60:
        return _CACHE["d"]
    with open(_DATA, "r", encoding="utf-8") as f:
        d = json.load(f)
    _CACHE.update(d=d, ts=now)
    return d


# ---------------- 周锚点 ----------------
def week_info(now=None):
    """今天是第几周（新生锚点）。返回 dict（week/span/semester/锚点口径）。"""
    d = _load()
    ac = d["academic_calendar"]
    now = now or datetime.date.today()
    anchor_s = ac.get("week1_monday_freshman", "2026-09-14")
    anchor = datetime.date.fromisoformat(anchor_s)
    delta = (now - anchor).days
    if delta >= 0:
        week = delta // 7 + 1
        week_day = "周" + "一二三四五六日"[now.weekday()]
        return {"week": week, "week_day": week_day,
                "label": "第 %d 周 %s" % (week, week_day),
                "semester": ac.get("current_semester"), "anchor": anchor_s,
                "anchor_kind": "freshman"}
    # 学期未开始：距开学天数
    return {"week": 0, "label": "距新生开学还有 %d 天" % (-delta),
            "semester": ac.get("current_semester"), "anchor": anchor_s,
            "anchor_kind": "freshman", "days_until": -delta}


# ---------------- 校历事件 ----------------
def _ev_end(e):
    return e.get("end") or e.get("date")


def upcoming(days=60, today=None):
    """未来 N 天的事件（含进行中）。按开始日期升序。"""
    d = _load()
    today = today or datetime.date.today()
    until = today + datetime.timedelta(days=days)
    out = []
    for e in d["academic_calendar"].get("events", []):
        try:
            s = datetime.date.fromisoformat(e["date"])
            en = datetime.date.fromisoformat(_ev_end(e))
        except (KeyError, ValueError):
            continue
        if en >= today and s <= until:
            out.append(e)
    out.sort(key=lambda e: e["date"])
    return out


def import_calendar(days=120, store_mod=None):
    """未来事件 → 提醒库（幂等）。返回 (imported, skipped)。

    规则：
      - 只导开始日在今天及以后、days 天内的事件（过去的/太远的不导）
      - remind_at = 事件开始日 08:00；区间事件 text 里带「（至 M-D）」
      - text 统一「[校历] 名字」前缀，查重按同 text + source=csu（重复调用不重复导）
    """
    import store as _store
    store_mod = store_mod or _store
    today = datetime.date.today()
    imported = skipped = 0
    for e in upcoming(days):
        try:
            s = datetime.date.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        if s < today:
            continue
        en = _ev_end(e)
        tail = ("（至 %s）" % en[5:].replace("-", "-")) if (e.get("end") and en != e["date"]) else ""
        text = "[校历] %s%s" % (e["name"], tail)
        remind_at = "%sT08:00:00" % e["date"]
        if _note_exists(store_mod, text):
            skipped += 1
            continue
        store_mod.add_note(text, source="csu",
                           tags=["校历", e.get("type", "其他")],
                           extra={"remind_at": remind_at})
        imported += 1
    return imported, skipped


def _note_exists(store_mod, text, title_mode=False):
    """查重：精确 text 匹配；title_mode=True 时按「第一行 == text」匹配
    （速查笔记是标题+多行正文，正文可能被更新过，按标题行查重）。"""
    try:
        for n in store_mod.list_notes():
            if n.get("source") != "csu":
                continue
            t = (n.get("text") or "").strip()
            if t == text or (title_mode and t.splitlines()[:1] == [text]):
                return True
    except Exception as e:
        log.info("csu note exists check err: %s", e)
        return True   # 查重失败时宁可跳过（不重复灌库）
    return False


# ---------------- 速查 ----------------
def _hit(obj, keys, q):
    q = (q or "").strip().lower()
    if not q:
        return True
    blob = " ".join(str(obj.get(k) or "") for k in keys).lower()
    return q in blob


def quick(q, limit=8):
    """奖学金/竞赛/综测加分/推免 统一速查。返回分组 dict。"""
    d = _load()
    out = {"scholarships": [], "competitions": [], "bonuses": [], "pending": []}
    for s in d.get("scholarships", []):
        if _hit(s, ("name", "level", "amount", "requirement", "quota", "window"), q):
            amt = s.get("amount")
            amt = "{:,.0f} 元".format(float(amt)) if str(amt).replace(".", "").replace(",", "").isdigit() else (amt or "待核实")
            out["scholarships"].append(
                "%s｜%s｜额度：%s｜条件：%s｜窗口：%s"
                % (s.get("name"), s.get("level", ""), amt,
                   (s.get("requirement") or "")[:60], s.get("window", "")))
    for c in d.get("competitions", []):
        if _hit(c, ("name", "level", "window", "team", "csu_strength",
                    "tuimian_points", "note"), q):
            tm = c.get("tuimian_points")
            tm = tm if tm not in (None, "", "无", "待核实") else "详见学院细则"
            out["competitions"].append(
                "%s｜%s｜%s｜%s｜推免加分：%s"
                % (c.get("name"), c.get("level", ""), c.get("window", ""),
                   c.get("team", ""), tm))
    comp = d.get("assessment_and_promotion", {}).get("comprehensive", {})
    for b in comp.get("bonuses", []):
        if _hit(b, ("item", "cap"), q):
            out["bonuses"].append("%s = %s 分（%s）"
                                  % (b.get("item"), b.get("points"), b.get("cap", "")))
    for p in d.get("pending_verification", [])[:53]:
        if _hit(p, ("item",), q):
            out["pending"].append(p.get("item", ""))
    for k in out:
        out[k] = out[k][:limit]
    return out


def pending():
    """待核实清单（如实展示，不阻塞）。"""
    return [p.get("item", "") for p in _load().get("pending_verification", [])]


# ---------------- 速查笔记种子（问路远可检索） ----------------
def seed_notes(store_mod=None):
    """把奖学金/竞赛/综测速查各写成一条汇总笔记（幂等，存在即跳过）。"""
    import store as _store
    store_mod = store_mod or _store
    d = _load()
    comp = d.get("assessment_and_promotion", {}).get("comprehensive", {})
    seeds = []

    lines = []
    for s in d.get("scholarships", []):
        lines.append("· %s（%s）额度 %s｜%s"
                     % (s.get("name"), s.get("level", ""), s.get("amount", "待核实"),
                        (s.get("requirement") or "")[:70]))
    seeds.append(("[速查·奖学金] CSU 本科生奖学金一览（09-14 整理，个人条件以学院通知为准）",
                  "\n".join(lines), ["速查", "奖学金"]))

    lines = []
    for c in d.get("competitions", []):
        lines.append("· %s（%s）%s｜%s｜推免加分 %s"
                     % (c.get("name"), c.get("level", ""), c.get("window", ""),
                        c.get("team", ""), c.get("tuimian_points", "待核实")))
    seeds.append(("[速查·竞赛] 大学生竞赛目录与时间窗（09-14 整理）",
                  "\n".join(lines), ["速查", "竞赛"]))

    lines = ["综测公式：" + (comp.get("formula") or "待核实"), ""]
    for b in comp.get("bonuses", []):
        lines.append("· %s = %s 分（%s）" % (b.get("item"), b.get("points"), b.get("cap", "")))
    lines.append("")
    lines.append("推免：" + (d.get("assessment_and_promotion", {}).get("tuimian", {})
                            .get("formula") or "待核实"))
    seeds.append(("[速查·综测] 综合测评加分项与推免公式（09-14 整理，7 院样本，个人细则待核实）",
                  "\n".join(lines), ["速查", "综测"]))

    imported = skipped = 0
    for title, body, tags in seeds:
        full = title + "\n" + body
        if _note_exists(store_mod, title, title_mode=True):
            skipped += 1
            continue
        store_mod.add_note(full, source="csu", tags=tags)
        imported += 1
    return imported, skipped
