# -*- coding: utf-8 -*-
"""Syncthing 冲突裁决（SYNC_FORMAT v2 §10.5）：列出 .sync-conflict 对，供面板「二选一」。
裁决 = 胜者写回本体文件名，败者挪进 data/conflict_trash/（隔离区，**永不物理删**——
撤销=从隔离区挪回来即可）。孤儿冲突（无本体）可收养（转正为本体）或隔离。
扫描范围：data/notes（笔记+实体）与 data/notes/contacts。"""
import os
import glob
import json
import shutil
import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
_SCAN_DIRS = [os.path.join(_BASE, "data", "notes"),
              os.path.join(_BASE, "data", "notes", "contacts")]
_TRASH = os.path.join(_BASE, "data", "conflict_trash")
_MARK = ".sync-conflict"


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _base_of(fname):
    """冲突文件名 → 本体文件名（X.sync-conflict-20260914-...json → X.json）。"""
    i = fname.find(_MARK)
    if i <= 0:
        return None
    stem, ext = os.path.splitext(fname[:i]), os.path.splitext(fname)[1]
    return stem[0] + ext


def list_conflicts():
    """全部冲突条目。有本体=成对（可对照）；无本体=孤儿（可收养/隔离）。"""
    out = []
    seen = set()
    for d in _SCAN_DIRS:
        for fp in glob.glob(os.path.join(d, "*")):
            fname = os.path.basename(fp)
            if _MARK not in fname or not os.path.isfile(fp):
                continue
            base = _base_of(fname)
            base_path = os.path.join(os.path.dirname(fp), base) if base else None
            has_base = bool(base_path and os.path.isfile(base_path))
            st = os.stat(fp)
            item = {
                "conflict": fname, "dir": os.path.relpath(os.path.dirname(fp), d),
                "base": base if has_base else None,
                "conflict_mtime": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "conflict_size": st.st_size,
                "conflict_json": _read_json(fp),
                "base_json": _read_json(base_path) if has_base else None,
                "orphan": not has_base,
            }
            if has_base:
                bst = os.stat(base_path)
                item["base_mtime"] = datetime.datetime.fromtimestamp(bst.st_mtime).isoformat(timespec="seconds")
                item["base_size"] = bst.st_size
            out.append(item)
            seen.add((os.path.dirname(fp), fname))
    out.sort(key=lambda x: x["conflict_mtime"], reverse=True)
    return out


def _find(conflict):
    for d in _SCAN_DIRS:
        fp = os.path.join(d, conflict)
        if os.path.isfile(fp):
            return fp
    return None


def resolve(conflict, keep):
    """裁决一条。keep='base' 本体为准 / 'conflict' 冲突副本为准 / 'discard' 仅孤儿可用（隔离丢弃）。
    胜者内容写回本体名；败者挪 data/conflict_trash/（带时间戳防重名）。
    孤儿 + keep='conflict' = 收养（冲突副本转正为本体名）。"""
    src = _find(conflict)
    if not src:
        return None
    base = _base_of(conflict)
    if not base:
        return None
    base_path = os.path.join(os.path.dirname(src), base)
    has_base = os.path.isfile(base_path)
    if keep not in ("base", "conflict", "discard"):
        return None
    if keep == "base" and not has_base:
        return None
    if keep == "discard" and has_base:
        return None  # discard 只给孤儿用；成对冲突必须二选一
    os.makedirs(_TRASH, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if keep == "discard":
        shutil.move(src, os.path.join(_TRASH, ts + "_" + conflict))
        return {"kept": None, "quarantined": conflict, "trash_dir": "data/conflict_trash"}
    if keep == "base":
        # 本体为准：本体不动，冲突副本进隔离区
        loser, kept = src, base_path
        shutil.move(src, os.path.join(_TRASH, ts + "_" + conflict))
    else:
        # 冲突副本为准：副本内容写回本体名；被顶掉的本体（若有）进隔离区
        with open(src, "rb") as f:
            data = f.read()
        if has_base:
            shutil.move(base_path, os.path.join(_TRASH, ts + "_" + base))
        with open(base_path, "wb") as f:
            f.write(data)
        os.remove(src)
        loser, kept = (os.path.join(_TRASH, ts + "_" + base) if has_base else None), base_path
    return {"kept": os.path.basename(kept), "quarantined": os.path.basename(loser) if loser else None,
            "trash_dir": "data/conflict_trash"}
