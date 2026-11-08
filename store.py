"""路远记事存储：每条记事一个 JSON 文件，落在 data/notes/。
每条独立成文件 → Syncthing 双向同步时绝不会整库冲突。"""
import json
import os
import glob
import uuid
import datetime
import threading

_BASE = os.path.dirname(os.path.abspath(__file__))
_LOCK = threading.Lock()
_cfg_cache = None


def _load_cfg():
    global _cfg_cache
    if _cfg_cache is None:
        with open(os.path.join(_BASE, "config.json"), "r", encoding="utf-8") as f:
            _cfg_cache = json.load(f)
    return _cfg_cache


def notes_dir():
    d = os.path.join(_BASE, _load_cfg().get("notes_dir", "data/notes"))
    os.makedirs(d, exist_ok=True)
    return d


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _note_files():
    """全部笔记 JSON 文件，排除 Syncthing 冲突副本（*.sync-conflict-*）。
    冲突副本此前被扫描器当成新笔记、面板上出现重复条目（与 v1.28a 联系人侧
    同款 bug），v1.31 统一排除；副本文件本身仍留在磁盘（SYNC_FORMAT 第四节：
    旧副本保留待人工合并）。"""
    return [f for f in glob.glob(os.path.join(notes_dir(), "*.json"))
            if ".sync-conflict" not in os.path.basename(f)]


def add_note(text, source="voice", tags=None, extra=None):
    """新增一条记事，返回 note dict；空文本返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    note = {
        "id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "text": text,
        "source": source,
        "tags": tags or [],
        # SYNC_FORMAT 归一化（数据体检建议）：新笔记一律带全契约字段，旧笔记靠读取兜底
        "device": "pc",
        "schema": 1,
        "updated_at": _now_iso(),
    }
    if extra:
        note.update(extra)
    fname = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + note["id"][:8] + ".json"
    path = os.path.join(notes_dir(), fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(note, f, ensure_ascii=False, indent=2)
    return note


def _read_note(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_notes(limit=None, reverse=True, tag=None, trash=False, ondate=None):
    """trash=False 默认隐藏软删笔记；trash=True 只看回收站；ondate='YYYY-MM-DD' 只看那天。"""
    files = _note_files()
    notes = []
    for fp in files:
        n = _read_note(fp)
        # 2026-09-14 P-todo：带 kind 字段的是 SYNC_FORMAT 实体（todo/expense/course）不是笔记。
        # todo 有 text 字段，会被当普通笔记捞进面板（expense 无 text 天然跳过，掩盖了这个洞）。
        if n and isinstance(n, dict) and n.get("text") and not n.get("kind"):
            is_del = bool(n.get("deleted"))
            if trash != is_del:
                continue
            if tag and tag not in (n.get("tags") or []):
                continue
            if ondate and not str(n.get("created_at", "")).startswith(ondate):
                continue
            n["_file"] = os.path.basename(fp)
            notes.append(n)
    notes.sort(key=lambda n: n.get("created_at", ""), reverse=reverse)
    if limit:
        notes = notes[:limit]
    return notes


def get_note(nid):
    for n in list_notes(limit=None):
        if n.get("id") == nid:
            return n
    return None


def update_note(nid, text):
    """按 id 修改记事正文，保留其它字段；成功返回更新后的 note，否则 None。"""
    text = (text or "").strip()
    if not text:
        return None
    for fp in _note_files():
        n = _read_note(fp)
        if n and n.get("id") == nid:
            n["text"] = text
            n["updated_at"] = _now_iso()
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(n, f, ensure_ascii=False, indent=2)
            return n
    return None


def delete_note(nid):
    for fp in _note_files():
        n = _read_note(fp)
        if n and n.get("id") == nid:
            try:
                os.remove(fp)
                return True
            except OSError:
                return False
    return False


def delete_many(ids):
    """批量删除，ids 为 list/tuple；返回成功删除的数量。"""
    ids = set(ids or [])
    if not ids:
        return 0
    n = 0
    for fp in _note_files():
        n_ = _read_note(fp)
        if n_ and n_.get("id") in ids:
            try:
                os.remove(fp)
                n += 1
            except OSError:
                pass
    return n


def set_images(nid, images):
    """设置笔记关联图片（相对路径列表）。"""
    fp, n = _find_file(nid)
    if not n:
        return None
    if images:
        n["images"] = [str(i) for i in images]
    else:
        n.pop("images", None)
    _write_note(fp, n)
    return n


def soft_delete(nid):
    """软删：置 deleted=true，文件保留（SYNC_FORMAT 第四节）。返回 note 或 None。"""
    fp, n = _find_file(nid)
    if not n:
        return None
    n["deleted"] = True
    n["updated_at"] = _now_iso()
    _write_note(fp, n)
    return n


def restore_note(nid):
    """从回收站恢复。"""
    fp, n = _find_file(nid)
    if not n:
        return None
    n.pop("deleted", None)
    n["updated_at"] = _now_iso()
    _write_note(fp, n)
    return n


def purge_note(nid):
    """物理删除（彻底清除，仅回收站内使用）。"""
    fp, n = _find_file(nid)
    if not n:
        return False
    try:
        os.remove(fp)
        return True
    except OSError:
        return False


def purge_old_trash(days=30, now=None):
    """回收站自动清理：软删超过 days 天的彻底删除（配合每日备份兜底）。
    返回清除条数。删除时间以 updated_at 为准（软删时必写），缺失用 created_at 兜底。"""
    now = now or datetime.datetime.now().astimezone()
    out = 0
    for n in list_notes(trash=True, limit=None):
        stamp = n.get("updated_at") or n.get("created_at") or ""
        try:
            t = datetime.datetime.fromisoformat(stamp)
        except (ValueError, TypeError):
            continue
        if t.tzinfo is None:
            t = t.astimezone()
        if (now - t).days >= days and purge_note(n["id"]):
            out += 1
    return out


def soft_delete_many(ids):
    ids = set(ids or [])
    if not ids:
        return 0
    n = 0
    for fp in _note_files():
        n_ = _read_note(fp)
        if n_ and n_.get("id") in ids and not n_.get("deleted"):
            n_["deleted"] = True
            n_["updated_at"] = _now_iso()
            _write_note(fp, n_)
            n += 1
    return n


def restore_many(ids):
    """批量从回收站恢复（v1.37，回收站批量工具条）。返回恢复条数。"""
    ids = set(ids or [])
    if not ids:
        return 0
    n = 0
    for fp in _note_files():
        n_ = _read_note(fp)
        if n_ and n_.get("id") in ids and n_.get("deleted"):
            n_.pop("deleted", None)
            n_["updated_at"] = _now_iso()
            _write_note(fp, n_)
            n += 1
    return n


def purge_many(ids):
    """批量彻底删除——只接受已在回收站（deleted=true）的条目，防误删正常笔记。"""
    ids = set(ids or [])
    if not ids:
        return 0
    n = 0
    for fp in _note_files():
        n_ = _read_note(fp)
        if n_ and n_.get("id") in ids and n_.get("deleted"):
            try:
                os.remove(fp)
                n += 1
            except OSError:
                pass
    return n


def note_dates():
    """所有有笔记的日期 + 条数（含软删），新日期在前。供面板日期跳转。"""
    dates = {}
    for fp in _note_files():
        n = _read_note(fp)
        if n and isinstance(n, dict) and n.get("text") and not n.get("kind"):
            d = str(n.get("created_at", ""))[:10]
            if d:
                dates[d] = dates.get(d, 0) + 1
    return [{"date": d, "count": c} for d, c in
            sorted(dates.items(), reverse=True)]


# ---------------- 分类列表（用户自定义，存 categories.txt） ----------------
_CATEGORIES_FILE = os.path.join(_BASE, "categories.txt")
_DEFAULT_CATEGORIES = ["待办", "购物", "想法", "日常", "写作素材"]


def read_categories():
    try:
        with open(_CATEGORIES_FILE, "r", encoding="utf-8") as f:
            cats = [ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")]
    except FileNotFoundError:
        cats = list(_DEFAULT_CATEGORIES)
        write_categories(cats)
    return cats or list(_DEFAULT_CATEGORIES)


def write_categories(cats):
    cats = [str(c).strip() for c in (cats or []) if str(c).strip()]
    if not cats:
        cats = list(_DEFAULT_CATEGORIES)
    with open(_CATEGORIES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(cats) + "\n")
    return cats


def organize_note(nid, block):
    """把 ✨整理块 追加到正文后（若已有整理块则替换旧块，原文始终保留）。"""
    fp, n = _find_file(nid)
    if not n:
        return None
    text = n.get("text", "")
    sep = "\n\n---- ✨ 整理 ----\n\n"
    if sep in text:
        text = text.split(sep)[0].rstrip()
    n["text"] = text + block
    n["updated_at"] = _now_iso()
    _write_note(fp, n)
    return n


def search_notes(q):
    q = (q or "").strip().lower()
    if not q:
        return list_notes()
    out = []
    for n in list_notes():
        hay = (n.get("text", "") + " " + " ".join(n.get("tags", []))).lower()
        if q in hay:
            out.append(n)
    return out


def build_merged_text(notes):
    """把多条笔记拼成给模型看的合并素材（带日期，便于模型区分时段）。
    只读，不落盘。传进来的 notes 需已按时间正序。"""
    lines = []
    for n in notes:
        d = (n.get("created_at") or "")[:10]
        t = (n.get("text") or "").split("\n\n---- ✨ 整理 ----\n\n")[0].strip()
        t = t.replace("\n", " ")
        lines.append("%s %s" % (d, t))
    return "\n".join(lines)


def merge_notes(ids, merged_text, tags=None, archive_tag="已合并"):
    """一键合并整理：新建一条汇总笔记，原始笔记打归档标签并软删（可恢复）。

    参数：
      ids          参与合并的原始笔记 id 列表
      merged_text  已经由模型生成好的汇总正文
      tags         汇总笔记的标签（默认沿用原笔记的标签并集）
      archive_tag  打到原始笔记上的归档标签

    返回 {note, archived, missing}；一条都没命中返回 None。
    安全：原始笔记只做「软删 + 打标签」，绝不物理删除，回收站可整体恢复。"""
    ids = [i for i in (ids or []) if i]
    if not ids or not (merged_text or "").strip():
        return None
    srcs, missing = [], []
    for i in ids:
        n = get_note(i)
        if n:
            srcs.append(n)
        else:
            missing.append(i)
    if not srcs:
        return None
    srcs.sort(key=lambda n: n.get("created_at") or "")
    if tags is None:
        seen = []
        for n in srcs:
            for t in (n.get("tags") or []):
                if t not in seen:
                    seen.append(t)
        tags = seen
    note = add_note(merged_text.strip(), source="merge",
                    tags=list(tags) + ["合并生成"],
                    extra={"merged_from": [n["id"] for n in srcs]})
    archived = []
    for n in srcs:
        add_tag(n["id"], archive_tag)
        if soft_delete(n["id"]):
            archived.append(n["id"])
    return {"note": note, "archived": archived, "missing": missing}


# ---------------- 提醒（SYNC_FORMAT 可选字段 remind_at / remind_fired） ----------------
def _find_file(nid):
    for fp in _note_files():
        n = _read_note(fp)
        if n and n.get("id") == nid:
            return fp, n
    return None, None


def _write_note(fp, n):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(n, f, ensure_ascii=False, indent=2)


def set_reminder(nid, remind_at):
    """设置/取消提醒。remind_at 为 ISO8601 字符串；None/空 = 取消。成功返回 note。"""
    fp, n = _find_file(nid)
    if not n:
        return None
    if remind_at:
        n["remind_at"] = remind_at
        n["remind_fired"] = False
    else:
        n.pop("remind_at", None)
        n.pop("remind_fired", None)
    _write_note(fp, n)
    return n


def due_reminders(now=None):
    """所有已到期但尚未触发过的提醒。"""
    now = now or datetime.datetime.now().astimezone()
    out = []
    for n in list_notes(limit=None):
        ra = n.get("remind_at")
        if not ra or n.get("remind_fired"):
            continue
        try:
            t = datetime.datetime.fromisoformat(ra)
        except (ValueError, TypeError):
            continue
        if t.tzinfo is None:
            t = t.astimezone()
        if t <= now:
            out.append(n)
    return out


def mark_reminder_fired(nid):
    fp, n = _find_file(nid)
    if not n:
        return None
    n["remind_fired"] = True
    _write_note(fp, n)
    return n


def add_tag(nid, tag):
    """给记事追加一个标签（已存在则不动）。成功返回 note。"""
    tag = (tag or "").strip()
    if not tag:
        return None
    fp, n = _find_file(nid)
    if not n:
        return None
    tags = n.get("tags") or []
    if tag not in tags:
        tags.append(tag)
        n["tags"] = tags
        _write_note(fp, n)
    return n


def set_field(nid, key, value):
    """设置笔记扩展字段（value=None=删除该字段）。PC 自有状态字段用
    （如稍后读 rl_state）；SYNC_FORMAT：未知字段两端一律忽略，零契约影响。"""
    fp, n = _find_file(nid)
    if not n:
        return None
    if value is None:
        n.pop(key, None)
    else:
        n[key] = value
    n["updated_at"] = _now_iso()
    _write_note(fp, n)
    return n
