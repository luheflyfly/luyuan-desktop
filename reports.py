# -*- coding: utf-8 -*-
"""路远远汇报（SYNC_FORMAT §10.6）：kind:"report" 一条一文件，report_<id8>.json 落同步根目录。
路远远（luyuan3\\路远助手）产出：晨报/新收录/提醒/管家讲解/群简报等，替代原 QQ 私聊播报（2026-10-19 路河拍板：QQ 不留）。
两端同看：PC 工作台「路远远」页签 + 手机 App；未知 kind 端安全跳过（v2 兼容铁律）。
⚠️ 与笔记同目录，但绝不写笔记路径；笔记扫描器按 kind 字段排除（同 todo 款）。
已读纪律：谁点谁写——fresh 读盘只改 read/read_at，bump updated_at 回写；两端都点只分先后，不冲突（同文件双写走 updated_at 新者胜）。"""
import os
import glob
import json
import datetime
import threading

_BASE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(_BASE, "data", "notes")   # data/notes 即 Syncthing 同步根目录（同 todo/expense/course）
_LOCK = threading.Lock()
_KEEP = 500                                    # 汇报容量上限：超出按最老先软删（防同步根无限膨胀）


def _now_iso():
    # 微秒级：同秒连写（管家批量派工）不会在容量封顶排序里打平
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def _dir():
    os.makedirs(_DIR, exist_ok=True)
    return _DIR


def _read(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("kind") != "report":
        return None  # 未知 kind / 坏文件：安全跳过
    return d


def _all_files():
    return [f for f in glob.glob(os.path.join(_dir(), "report_*.json"))
            if ".sync-conflict" not in os.path.basename(f)]


def _write(fp, r):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)


def list_reports(include_read=True, limit=300):
    """全部汇报（新在前）。缺省连已读一起给（页签要分未读/已读两段）；limit 限条数防面板卡顿。"""
    out = []
    for fp in _all_files():
        r = _read(fp)
        if not r or r.get("deleted"):
            continue
        if not include_read and not r.get("read"):
            continue
        r["_file"] = os.path.basename(fp)
        out.append(r)
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out[:limit] if limit else out


def overview():
    """「路远远」页签数据：全部汇报 + 未读数。"""
    rs = list_reports(include_read=True, limit=0)
    unread = [r for r in rs if not r.get("read")]
    return {"reports": rs[:300], "unread": len(unread), "count": len(rs)}


def unread_count():
    """侧栏红点用：只数不搬全文。"""
    n = 0
    for fp in _all_files():
        r = _read(fp)
        if r and not r.get("deleted") and not r.get("read"):
            n += 1
    return n


def create(title, text, category="", ref=None, source="luyuanyuan", device="pc", summary=""):
    """写一条新汇报（路远远侧经同步文件夹落盘，也供 PC 本地调用）。只新增文件，不碰旧文件——Syncthing 零冲突。"""
    import uuid
    rid = str(uuid.uuid4())
    r = {
        "kind": "report",
        "id": rid,
        "schema": 3,
        "device": device,
        "deleted": False,
        "title": str(title or "")[:30] or "（无题）",
        "summary": str(summary or "")[:60],
        "category": str(category or "")[:20],
        "text": str(text or ""),
        "ref": ref or None,
        "source": source,
        "read": False,
        "read_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    fp = os.path.join(_dir(), "report_%s.json" % rid[:8])
    with _LOCK:
        _write(fp, r)
        _prune_locked()
    return r


def _prune_locked():
    """容量守门：超 KEEP 条按最老先软删（deleted 墓碑，不物理删——同 todo 删除纪律）。"""
    rs = []
    for fp in _all_files():
        r = _read(fp)
        if r and not r.get("deleted"):
            rs.append((r.get("created_at", ""), fp, r))
    rs.sort(key=lambda x: x[0])
    extra = len(rs) - _KEEP
    for _, fp, r in rs[:max(0, extra)]:
        r["deleted"] = True
        r["updated_at"] = _now_iso()
        _write(fp, r)


def mark_read(rid, read=True):
    """标已读/未读：fresh 读盘只改目标字段（vc98 写入纪律），Syncthing 带回手机端。"""
    with _LOCK:
        for fp in _all_files():
            r = _read(fp)
            if r and r.get("id") == rid:
                r["read"] = bool(read)
                r["read_at"] = _now_iso() if read else None
                r["updated_at"] = _now_iso()
                _write(fp, r)
                return r
    return None


def read_all():
    """全部已读（页签「全标已读」按钮）。"""
    n = 0
    with _LOCK:
        for fp in _all_files():
            r = _read(fp)
            if r and not r.get("deleted") and not r.get("read"):
                r["read"] = True
                r["read_at"] = _now_iso()
                r["updated_at"] = _now_iso()
                _write(fp, r)
                n += 1
    return n


def discard(rid):
    """删一条：物理删（同 PC 端 todo ✗不要 款；汇报是一次性读物，不留墓碑省同步根）。"""
    with _LOCK:
        for fp in _all_files():
            r = _read(fp)
            if r and r.get("id") == rid:
                try:
                    os.remove(fp)
                    return True
                except OSError:
                    return False
    return False
