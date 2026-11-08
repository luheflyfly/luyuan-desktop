#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新旧对照：线上 8777（旧）vs 影子端口（新）逐端点比对。

重构的每个阶段都要跑它 —— 这是"没有偷偷改坏东西"的唯一证据。

    .venv\\Scripts\\python.exe tests\\compare.py
    ... --old http://127.0.0.1:8777 --new http://127.0.0.1:8799 --strict

比什么（只比能比的）：
  * HTTP 状态码
  * 顶层字段集合
  * 集合型端点：元素 id 集合（多/少/分别列出）
  * 计数字段：逐项数值
不比：时间戳、顺序、内部字段（_file 之类）、文案。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

# (名称, 路径, 集合字段名 or None)
ENDPOINTS: list[tuple[str, str, str | None]] = [
    ("counts",       "/api/counts",                     None),
    ("note_dates",   "/api/note_dates",                 None),
    ("notes",        "/api/notes?limit=500",            "notes"),
    ("notes_diary",  "/api/notes?limit=500&diary=1",    "notes"),
    ("notes_trash",  "/api/notes?limit=500&trash=1", "notes"),
    ("notes_today",  "/api/notes?limit=500&ondate=2026-09-28", "notes"),
    ("search",       "/api/search?q=%E7%9A%84",         "notes"),
    ("courses",      "/api/courses",                    "courses"),
    ("todos",        "/api/todos",                      "todos"),
    ("expenses",     "/api/expenses",                   "items"),
    ("expenses_sep", "/api/expenses?month=2026-09",     "items"),
    ("diary_today",  "/api/diary/today",                None),
    ("diary_recent", "/api/diary/recent",               "notes"),
    # 有意差异：新实现脱敏（key 只出掩码），旧实现吐明文 —— 见 luyuan/web/routes/config.py
    ("config",       "/api/config",                     None),
]

# 允许不一致的端点（有意的设计差异，不算回归）
EXPECT_DIFF = {"config"}


def get(base: str, path: str, timeout: float = 15.0):
    url = base.rstrip("/") + path
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def ids_of(payload, key: str) -> list[str]:
    arr = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(arr, list):
        return []
    return sorted(str(x.get("id")) for x in arr if isinstance(x, dict) and x.get("id"))


def diff_sets(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    so, sn = set(old), set(new)
    return sorted(so - sn), sorted(sn - so)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="http://127.0.0.1:8777")
    ap.add_argument("--new", default="http://127.0.0.1:8799")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    print(f"新旧对照 · old={args.old}  new={args.new}")
    print("=" * 78)
    problems = 0

    for name, path, key in ENDPOINTS:
        expected = name in EXPECT_DIFF
        tag = "[ OK*]" if expected else None

        def ok(msg: str):
            print(f"{tag or '[ OK ]'} {name:<12} {msg}")

        def bad(msg: str):
            nonlocal problems
            if not expected:
                problems += 1
            print(f"{'[DIFF*]' if expected else '[DIFF]'} {name:<12} {msg}")

        so, po = get(args.old, path)
        sn, pn = get(args.new, path)

        if so != sn or po is None or pn is None:
            bad(f"状态 old={so} new={sn}  新旧任一取不到")
            continue

        if key:
            oi, ni = ids_of(po, key), ids_of(pn, key)
            only_old, only_new = diff_sets(oi, ni)
            if not only_old and not only_new:
                ok(f"{len(oi):>3} 条，id 集合一致")
            else:
                bad(f"old={len(oi)} new={len(ni)}  旧独有 {len(only_old)} / 新独有 {len(only_new)}")
                for i in only_old[:5]:
                    print(f"          - 旧有  {i}")
                for i in only_new[:5]:
                    print(f"          + 新有  {i}")
            continue

        # 非集合端点：比字段集合和数值
        if not isinstance(po, dict) or not isinstance(pn, dict):
            ok("非对象响应")
            continue
        ko, kn = set(po), set(pn)
        if ko == kn and po == pn:
            ok("字段与数值全等")
            continue
        if ko != kn:
            bad(f"字段差异 仅旧={sorted(ko - kn)} 仅新={sorted(kn - ko)}")
        val_diff = {k: (po[k], pn[k]) for k in (ko & kn) if po[k] != pn[k]}
        if val_diff:
            bad(f"数值差异 {list(val_diff)[:4]}")
        if ko == kn and not val_diff:
            ok("一致")

    print("=" * 78)
    print("全部一致" if problems == 0 else f"共 {problems} 处差异"
          + ("（带 * 的是有意差异，不计入）" if EXPECT_DIFF else ""))
    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
