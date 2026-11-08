# -*- coding: utf-8 -*-
"""联系人存储：一人一 JSON，落在 data/contacts/（随 data/ 同步，格式见 SYNC_FORMAT 第八节）。"""
import os
import re
import uuid
import datetime
import threading

from pypinyin import lazy_pinyin

_BASE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(_BASE, "data", "notes", "contacts")  # 放 notes 子目录 → 随现有 Syncthing 同步，手机零操作
_LOCK = threading.Lock()


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _dir():
    os.makedirs(_DIR, exist_ok=True)
    return _DIR


def _letter(name):
    try:
        first = lazy_pinyin(name)[0]
        ch = first[0].upper() if first and first[0].isalpha() else "#"
    except Exception:
        ch = "#"
    return ch if ch.isalpha() else "#"


def _read(fp):
    import json
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write(fp, c):
    import json
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def _find(cid):
    for fp in _all_files():
        c = _read(fp)
        if c and c.get("id") == cid:
            return fp, c
    return None, None


def _all_files():
    import glob
    return sorted(f for f in glob.glob(os.path.join(_dir(), "*.json"))
                  if ".sync-conflict" not in os.path.basename(f))


def merge_conflict_copies():
    """合并 Syncthing 冲突副本（同名联系人）：todos/info 并集（勾选完成优先保留）、
    字段取较新，然后删除冲突副本。每次读列表前自愈一次。"""
    import glob
    import json as _json
    changed = False
    for fp in glob.glob(os.path.join(_dir(), "*.json")):
        base = os.path.basename(fp)
        if ".sync-conflict" not in base:
            continue
        cc = _read(fp)
        if not cc or not cc.get("name"):
            try:
                os.remove(fp)
            except OSError:
                pass
            continue
        name = cc["name"]
        main_fp, mc = _find_by_name(name)
        if not mc:
            # 主文件没了 → 冲突副本转正
            try:
                os.rename(fp, os.path.join(_dir(), "%s_%s.json" % (cc.get("letter", "X"), name)))
            except OSError:
                pass
            continue
        # todos 并集：id/text 归并，done=True 优先（保住手机上的勾选）
        merged = {}
        for t in mc.get("todos", []):
            merged[t.get("id") or t.get("text")] = t
        for t in cc.get("todos", []):
            k = t.get("id") or t.get("text")
            if k in merged:
                if t.get("done"):
                    merged[k]["done"] = True
                if t.get("remind_at") and not merged[k].get("remind_at"):
                    merged[k]["remind_at"] = t["remind_at"]
            else:
                merged[k] = t
        # 同文本再去重（不同 id 的重复条目），done=True 优先保留
        bytext = {}
        for t in merged.values():
            k = t.get("text", "")
            if k not in bytext or (t.get("done") and not bytext[k].get("done")):
                old_t = bytext.get(k)
                bytext[k] = t
                if old_t and old_t.get("remind_at") and not t.get("remind_at"):
                    bytext[k]["remind_at"] = old_t["remind_at"]
        mc["todos"] = list(bytext.values())
        info = list(dict.fromkeys((mc.get("info") or []) + (cc.get("info") or [])))
        if info:
            mc["info"] = info
        for k in ("phone", "wechat", "qq", "birthday", "group", "sid"):
            if not mc.get(k) and cc.get(k):
                mc[k] = cc[k]
        mc["updated_at"] = _now_iso()
        _write(main_fp, mc)
        try:
            os.remove(fp)
            changed = True
        except OSError:
            pass
    return changed


def _find_by_name(name):
    import glob
    for fp in glob.glob(os.path.join(_dir(), "*.json")):
        if ".sync-conflict" in os.path.basename(fp):
            continue
        c = _read(fp)
        if c and c.get("name") == name:
            return fp, c
    return None, None


# ---------------- 分组 / 学号（2026-09-13 新增） ----------------
# group：任一分组名（如「大学同班同学」），空=未分组
# sid  ：学号。存字符串（可能带前缀字母），排序时取前导数字比较
_SID_INFO_RE = re.compile(r"^学号\s*[:：]\s*(.*)$")


def _norm(c):
    """补齐新字段默认值，老数据（无 group/sid）也能被前端安全读取。"""
    if c is None:
        return None
    c.setdefault("group", "")
    c.setdefault("sid", "")
    if not isinstance(c.get("group"), str):
        c["group"] = str(c.get("group") or "")
    if not isinstance(c.get("sid"), str):
        c["sid"] = str(c.get("sid") or "")
    return c


def _sid_key(c):
    """排序键：(是否有学号, 学号数字, 名字)。没学号的排最后。"""
    s = str(c.get("sid") or "").strip()
    m = re.match(r"^(\d+)", s)
    if m:
        return (0, int(m.group(1)), c.get("name", ""))
    return (1, 0, c.get("name", ""))


def sync_sid_info(c):
    """让「个人信息」列表里的『学号：X』与 sid 字段保持一致。

    用户要求学号显示在「性别」后面，所以这里插到 男/女 那条之后；
    没有性别条目就追加到末尾。sid 清空则删掉这一行。"""
    sid = str(c.get("sid") or "").strip()
    info = [str(x) for x in (c.get("info") or [])]
    idx = next((i for i, s in enumerate(info) if _SID_INFO_RE.match(s)), None)
    if idx is not None:
        if sid:
            info[idx] = "学号：%s" % sid
        else:
            info.pop(idx)
    elif sid:
        sex_i = next((i for i, s in enumerate(info)
                      if s.strip() in ("男", "女")), None)
        line = "学号：%s" % sid
        if sex_i is None:
            info.append(line)
        else:
            info.insert(sex_i + 1, line)
    c["info"] = info
    return c


def list_contacts(q="", group=None, sort=None):
    """全部联系人。

    q      模糊匹配姓名/信息/待办
    group  只列出该分组的成员（None/空 = 全部）
    sort   "sid"=按学号 / "letter"=按拼音字母 / None=自动
           （选了分组就自动按学号，否则按拼音）
    """
    with _LOCK:
        pass
    try:
        merge_conflict_copies()
    except Exception:
        pass
    with _LOCK:
        out = []
        for fp in _all_files():
            c = _read(fp)
            if c:
                out.append(_norm(c))
    if q:
        q = q.strip().lower()
        out = [c for c in out if q in c.get("name", "").lower()
               or any(q in str(i).lower() for i in c.get("info", []))
               or any(q in t.get("text", "").lower() for t in c.get("todos", []))
               or q in (c.get("phone", "") + c.get("wechat", "") + c.get("qq", "") + c.get("birthday", "") + c.get("sid", "")).lower()]
    if group:
        out = [c for c in out if (c.get("group") or "") == group]
    mode = sort or ("sid" if group else "letter")
    if mode == "sid":
        out.sort(key=_sid_key)
    else:
        out.sort(key=lambda c: (c.get("letter", "#"), c.get("name", "")))
    return out


def list_groups():
    """所有非空分组 + 人数（人数多的在前，同人数按名字）。"""
    counts = {}
    for c in list_contacts():
        g = (c.get("group") or "").strip()
        if g:
            counts[g] = counts.get(g, 0) + 1
    return [{"name": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def get_contact(cid):
    with _LOCK:
        fp, c = _find(cid)
        return _norm(c) if c else None


def add_contact(name, group="", sid=""):
    name = (name or "").strip()
    if not name:
        return None
    with _LOCK:
        for fp in _all_files():
            c = _read(fp)
            if c and c.get("name") == name:
                return _norm(c)  # 已存在直接返回
        c = {
            "kind": "contact",   # SYNC_FORMAT v2
            "id": str(uuid.uuid4()),
            "name": name,
            "letter": _letter(name),
            "phone": "", "wechat": "", "qq": "", "birthday": "",
            "relation": "", "note": "",
            "group": str(group or "").strip(),   # 分组（如「大学同班同学」）
            "sid": str(sid or "").strip(),       # 学号
            "info": [], "todos": [],
            "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        sync_sid_info(c)
        _write(os.path.join(_dir(), "%s_%s.json" % (c["letter"], name)), c)
    return c


def update_contact(cid, fields):
    """更新基础字段（phone/wechat/qq/birthday/name/relation/note/group/sid/info）。"""
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return None
        for k in ("phone", "wechat", "qq", "birthday", "name", "relation",
                  "note", "group", "sid"):
            if k in (fields or {}):
                c[k] = str(fields[k]).strip()
        if "info" in (fields or {}) and isinstance(fields["info"], list):
            c["info"] = [str(i) for i in fields["info"]]
        # 学号改动要同步「个人信息」里那行「学号：X」（用户要求它跟在性别后面）
        if "sid" in (fields or {}):
            sync_sid_info(c)
        if c.get("name"):
            c["letter"] = _letter(c["name"])
            newfp = os.path.join(_dir(), "%s_%s.json" % (c["letter"], c["name"]))
            if newfp != fp:
                try:
                    os.remove(fp)
                except OSError:
                    pass
                fp = newfp
        c["updated_at"] = _now_iso()
        _write(fp, c)
    return _norm(c)


def add_info(cid, text):
    """追加一条个人信息（去重）。"""
    text = (text or "").strip()
    if not text:
        return None
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return None
        if text not in c.get("info", []):
            c.setdefault("info", []).append(text)
        c["updated_at"] = _now_iso()
        _write(fp, c)
    return c


def delete_contact(cid):
    with _LOCK:
        fp, c = _find(cid)
        if not fp:
            return False
        try:
            os.remove(fp)
            return True
        except OSError:
            return False


def add_todo(cid, text, remind_at=None):
    text = (text or "").strip()
    if not text:
        return None
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return None
        todo = {"id": str(uuid.uuid4())[:8], "text": text,
                "done": False, "created_at": _now_iso()}
        if remind_at:
            todo["remind_at"] = remind_at
            todo["reminded"] = False
        c.setdefault("todos", []).append(todo)
        c["updated_at"] = _now_iso()
        _write(fp, c)
    return todo


def toggle_todo(cid, tid, done=None):
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return None
        for t in c.get("todos", []):
            if t.get("id") == tid:
                t["done"] = (not t["done"]) if done is None else bool(done)
                c["updated_at"] = _now_iso()
                _write(fp, c)
                return t
    return None


def delete_todo(cid, tid):
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return False
        before = len(c.get("todos", []))
        c["todos"] = [t for t in c.get("todos", []) if t.get("id") != tid]
        if len(c["todos"]) != before:
            c["updated_at"] = _now_iso()
            _write(fp, c)
            return True
    return False


# ---------------- 主界面自动归入联系人 ----------------
INFO_RE = re.compile(
    r"^(.{1,20}?)的?(生日|电话|手机|手机号|微信|微信号|QQ|qq|备注)(?:是|为|叫|[:：])\s*(.+)$")

_INFO_KEY = {"生日": "birthday", "电话": "phone", "手机": "phone",
             "手机号": "phone", "微信": "wechat", "微信号": "wechat",
             "QQ": "qq", "qq": "qq", "备注": None}


def capture_for_contacts(cid_note_text):
    """扫描笔记文本，返回命中的联系人操作列表。
    返回 [{"contact":c, "kind":"info"|"todo", "detail":str}]；无命中返回 []。"""
    text = (cid_note_text or "").strip()
    if not text:
        return []
    hits = []
    for c in list_contacts():
        name = c.get("name", "")
        if not name or name not in text:
            continue
        m = INFO_RE.match(text)
        if m and m.group(1).endswith(name):
            key = m.group(2)
            value = m.group(3).strip().rstrip("。.,，")
            field = _INFO_KEY.get(key)
            detail = "%s：%s" % (key, value)
            hits.append({"contact": c, "kind": "info", "detail": detail,
                         "field": field, "value": value})
        else:
            hits.append({"contact": c, "kind": "todo", "detail": text})
    return hits


def find_mentioned_by_llm(text, names):
    """大模型对照花名册找笔记里提到的人（同音错字兜底）。
    返回 [(准确名字, 是否待办)]；失败/无命中返回 []。"""
    if not names or not (text or "").strip():
        return []
    import smart
    roster = "、".join(names)
    out = smart.chat([
        {"role": "system",
         "content": "你是记事分析器。联系人名单：" + roster + "。"
                    "判断用户记事里提到了名单中的哪几人（注意同音/近音错字，"
                    "如'谢凤您'其实可能是'谢凤林'），以及这是不是要去做的事。"
                    '只输出一行 JSON：{"names":["名单中的准确名字"],"todo":true 或 false}。'
                    "names 为空数组表示没提到任何人。"},
        {"role": "user", "content": text[:200]},
    ], num_predict=60, temperature=0)
    import re as _re
    m = _re.search(r"\{[^{}]*\}", out or "", _re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    todo = bool(data.get("todo"))
    # 模型可能原样回显错字名（谢凤您）→ 扫描回答里所有 2-4 字中文词，
    # 逐个与花名册做拼音模糊匹配（谢凤您 ≈ 谢凤林，编辑距离1）
    import re as _re2
    words = _re2.findall(r"[一-鿿]{2,4}", out or "")
    hit = []
    for n in names:
        if n in (out or "") or any(w == n or n in w for w in words):
            hit.append(n)
            continue
        if any(_py_similar(w, n) for w in words):
            hit.append(n)
    hit = list(dict.fromkeys(hit))
    return [(n, todo) for n in hit]


def _py_similar(a, b):
    """拼音串相似：相等或编辑距离 ≤ 1（人名同音错字级别）。"""
    try:
        from pypinyin import lazy_pinyin
        pa = "".join(lazy_pinyin(a)).lower()
        pb = "".join(lazy_pinyin(b)).lower()
    except Exception:
        return False
    return _edit_le1(pa, pb)


def _edit_le1(a, b):
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if i >= len(a) or a[i] != b[i]:
            return a[i:] == b[i + 1:] or a[i + 1:] == b[i + 1:]
    return True


def fuzzy_scan_text(text, names):
    """确定性扫描：笔记文本里是否有与联系人名拼音相近的片段（同音错字）。
    不依赖大模型，必命中。返回命中的联系人名列表。"""
    text = (text or "").strip()
    if not text or not names:
        return []
    from pypinyin import lazy_pinyin
    hit = []
    for n in names:
        if n in text:
            hit.append(n)
            continue
        try:
            pn = "".join(lazy_pinyin(n)).lower()
        except Exception:
            continue
        found = False
        for size in {max(2, len(n) - 1), len(n), len(n) + 1}:
            for i in range(0, max(1, len(text) - size + 1)):
                seg = text[i:i + size]
                if len(seg) < size or not re.match(r"^[一-鿿]+$", seg):
                    continue
                try:
                    ps = "".join(lazy_pinyin(seg)).lower()
                except Exception:
                    continue
                if _edit_le1(ps, pn):
                    found = True
                    break
            if found:
                break
        if found:
            hit.append(n)
    return hit


def judge_todo_by_llm(text):
    """大模型二次判断：这句记事到底是不是要去做的事（防小模型误判日常）。"""
    import smart
    out = smart.chat([
        {"role": "system",
         "content": "判断记事是不是'要去做的事'（要做/要帮/要交/要去/有期限=是；"
                    "已经发生的、单纯想法感想=不是）。只输出一行 JSON，格式：{\"todo\": true} 或 {\"todo\": false}\n"
                    "例：「明天交作业」→ {\"todo\": true}\n"
                    "例：「今天吃了火锅真辣」→ {\"todo\": false}\n"
                    "例：「下午要帮妈妈取快递」→ {\"todo\": true}\n"
                    "例：「今天陪爸看病，恢复得不错」→ {\"todo\": false}"},
        {"role": "user", "content": (text or "")[:200]},
    ], num_predict=30, temperature=0)
    import re as _re
    m = _re.search(r"\{[^{}]*\}", out or "", _re.S)
    if not m:
        return False
    try:
        return bool(json.loads(m.group(0)).get("todo"))
    except Exception:
        return False


# ---------------- 待办判定（确定性优先，LLM 兜底） ----------------
_CUE_RE = re.compile(r"(要|帮|带|交|买|取|送|提醒|记得|预约|别忘|去办|续费|还钱)")
_DONE_RE = re.compile(r"(帮|带|交|买|取|送|办)[^。，,！!]{0,5}了")


def is_todo_note(text, category=""):
    """判断笔记是否应作为联系人待办。确定性规则优先，LLM 只在拿不准时兜底。"""
    text = (text or "").strip()
    if not text:
        return False
    if category == "待办":
        return True
    if _CUE_RE.search(text) and not _DONE_RE.search(text):
        return True
    if category == "日常":
        return judge_todo_by_llm(text)
    return False


# ---------------- 待办提醒时间（v1.24 简易定时系统） ----------------
# 场景关键词 → 默认提醒时刻（没说具体时间时的兜底，可按习惯改）
DEFAULT_TIMES = [
    (re.compile(r"晚点|待会|等会"), -3, 0),   # 相对：3小时后（负数=相对小时）
    (re.compile(r"午饭|中饭"), 11, 0),
    (re.compile(r"晚饭"), 17, 0),
    (re.compile(r"早上|早饭"), 8, 0),
    (re.compile(r"下午"), 14, 0),
    (re.compile(r"晚上"), 19, 30),
    (re.compile(r"放学|下班"), 17, 0),
]


def suggest_remind_time(text, now=None):
    """从待办文本猜一个默认提醒时间（确定性规则，不用模型）。
    返回 ISO8601 字符串；猜不出返回 None。时间已过自动顺延到明天。"""
    now = now or datetime.datetime.now().astimezone()
    text = text or ""
    for pat, hh, mm in DEFAULT_TIMES:
        if pat.search(text):
            if hh < 0:   # 相对时间（如"晚点"=3小时后）
                dt = now + datetime.timedelta(hours=-hh)
            else:
                dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if dt <= now:
                    dt += datetime.timedelta(days=1)   # 已过 → 明天同一时间
            return dt.isoformat(timespec="seconds")
    return None


def snooze_todo(cid, tid, hours):
    """贪睡：提醒时间推到 now + hours 小时，允许再次提醒。"""
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return None
        for t in c.get("todos", []):
            if t.get("id") == tid:
                t["remind_at"] = (datetime.datetime.now().astimezone()
                                  + datetime.timedelta(hours=float(hours))
                                  ).isoformat(timespec="seconds")
                t["reminded"] = False
                _write(fp, c)
                return t
    return None


def due_contact_todos(now=None):
    """所有已到提醒时间、未提醒、未完成的联系人待办。
    返回 [{"contact":c, "todo":t}]。"""
    now = now or datetime.datetime.now().astimezone()
    out = []
    with _LOCK:
        for fp in _all_files():
            c = _read(fp)
            if not c:
                continue
            for t in c.get("todos", []):
                if t.get("done") or t.get("reminded") or not t.get("remind_at"):
                    continue
                try:
                    rt = datetime.datetime.fromisoformat(t["remind_at"])
                except (ValueError, TypeError):
                    continue
                if rt.tzinfo is None:
                    rt = rt.astimezone()
                if rt <= now:
                    out.append({"contact": c, "todo": t})
    return out


def pending_contact_todos():
    """全部未完成的联系人待办（不限提醒时间），出门感应用。
    返回 [{"contact":c, "todo":t}]。"""
    out = []
    with _LOCK:
        for fp in _all_files():
            c = _read(fp)
            if not c:
                continue
            for t in c.get("todos", []):
                if not t.get("done"):
                    out.append({"contact": c, "todo": t})
    return out


def mark_contact_todo_reminded(cid, tid):
    with _LOCK:
        fp, c = _find(cid)
        if not c:
            return None
        for t in c.get("todos", []):
            if t.get("id") == tid:
                t["reminded"] = True
                _write(fp, c)
                return t
    return None


# ---------------- 生日提醒（v1.5 轻量版：当天祝贺，不出错不吵人） ----------------
_BDAY_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})")


def parse_birthday(text):
    """从生日字段提取 (月, 日)。支持「10月20日」「11月3日」等自然写法；
    解析不出或非法返回 None（绝不因为格式怪而报错）。"""
    m = _BDAY_RE.search(text or "")
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    if 1 <= mo <= 12 and 1 <= d <= 31:
        return (mo, d)
    return None


def today_birthdays(now=None):
    """今天过生日的联系人列表。"""
    now = now or datetime.datetime.now()
    md = (now.month, now.day)
    out = []
    for c in list_contacts():
        if parse_birthday(c.get("birthday") or "") == md:
            out.append(c)
    return out


def upcoming_birthdays(days=3, now=None):
    """未来 days 天内（不含今天）要过生日的联系人。
    返回 [(contact, (月,日), 还有几天)]，按天数升序。跨月/跨年都按日历差算。"""
    _MDAY = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    now = now or datetime.datetime.now()
    out = []
    for c in list_contacts():
        md = parse_birthday(c.get("birthday") or "")
        if not md:
            continue
        day = min(md[1], _MDAY[md[0] - 1])      # 2月30/4月31 之类钳到月末
        try:
            nxt = datetime.datetime(now.year, md[0], day)
        except ValueError:                       # 平年 2月29 → 当作 2月28
            nxt = datetime.datetime(now.year, 2, 28)
        if nxt.date() <= now.date():
            try:
                nxt = datetime.datetime(now.year + 1, md[0], day)
            except ValueError:
                nxt = datetime.datetime(now.year + 1, 2, 28)
        delta = (nxt.date() - now.date()).days
        if 1 <= delta <= days:
            out.append((c, md, delta))
    out.sort(key=lambda x: x[2])
    return out