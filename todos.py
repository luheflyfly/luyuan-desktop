# -*- coding: utf-8 -*-
"""消息待办存储（SYNC_FORMAT v3 §10.4）：kind:"todo" 一条一文件，todo_<id8>.json 落同步根目录。
手机端（vc58 消息待办）确认后产出，PC 端读取 + 完成/丢弃回写；其他未知 kind 安全跳过。
⚠️ 与笔记同目录，但绝不写 data/notes 的笔记路径；笔记扫描器已按 kind 字段排除（2026-09-14 P-todo）。"""
import os
import glob
import json
import datetime
import threading

_BASE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(_BASE, "data", "notes")   # data/notes 即 Syncthing 同步根目录（同 expense/course）
_LOCK = threading.Lock()


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _dir():
    os.makedirs(_DIR, exist_ok=True)
    return _DIR


def _read(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("kind") != "todo":
        return None  # 未知 kind / 坏文件：安全跳过
    return d


def _all_files():
    return [f for f in glob.glob(os.path.join(_dir(), "todo_*.json"))
            if ".sync-conflict" not in os.path.basename(f)]


def _write(fp, t):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=2)


def list_todos(include_done=False):
    """全部消息待办。缺省只回未完成（新在前）；include_done=True 连已完成一起给。"""
    out = []
    for fp in _all_files():
        t = _read(fp)
        if not t or t.get("deleted"):
            continue
        if not include_done and t.get("done"):
            continue
        t["_file"] = os.path.basename(fp)
        out.append(t)
    out.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return out


def overview():
    """今日待办区数据：未完成全部（新在前）+ 今天已完成的（done_at 是今天）。"""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    undone, done_today = [], []
    for t in list_todos(include_done=True):
        if t.get("done"):
            if str(t.get("done_at", "")).startswith(today):
                done_today.append(t)
        else:
            undone.append(t)
    return {"todos": undone, "done_today": done_today, "count": len(undone)}


def mark_done(tid):
    """确认完成：回写 done=true + done_at（契约字段，Syncthing 带回手机端）。"""
    with _LOCK:
        for fp in _all_files():
            t = _read(fp)
            if t and t.get("id") == tid:
                t["done"] = True
                t["done_at"] = _now_iso()
                t["updated_at"] = _now_iso()
                _write(fp, t)
                return t
    return None


def unmark(tid):
    """取消完成（2026-09-18 挂账收尾，SYNC_FORMAT §10.4）：done 翻回 false + done_at 清空。
    手机端 vc98 起勾选走 fresh 读盘只改目标字段，本回写不会被冲掉。返回 todo 或 None。"""
    with _LOCK:
        for fp in _all_files():
            t = _read(fp)
            if t and t.get("id") == tid:
                t["done"] = False
                t["done_at"] = None
                t["updated_at"] = _now_iso()
                _write(fp, t)
                return t
    return None


def update_fields(tid, fields):
    """局部字段更新（vc127，路远远整理智能体专用）：白名单只放 topic/due_at/when_text。
    fresh 读盘→只改目标字段→bump updated_at 回写（与 mark_done 同纪律）；done/deleted 绝不进白名单。
    返回更新后的 todo 或 None。"""
    allow = {k: fields[k] for k in ("topic", "due_at", "when_text") if k in fields}
    if not allow:
        return None
    with _LOCK:
        for fp in _all_files():
            t = _read(fp)
            if t and t.get("id") == tid:
                t.update({k: (v if isinstance(v, str) else "") for k, v in allow.items()})
                t["updated_at"] = _now_iso()
                _write(fp, t)
                return t
    return None


def discard(tid):
    """丢弃：删文件（与手机端 ✗不要 行为一致，expense.delete 同款物理删）。"""
    with _LOCK:
        for fp in _all_files():
            t = _read(fp)
            if t and t.get("id") == tid:
                try:
                    os.remove(fp)
                    return True
                except OSError:
                    return False
    return False
