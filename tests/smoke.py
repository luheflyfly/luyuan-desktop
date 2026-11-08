#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""路远冒烟测试 —— 只读探测真实运行中的后端，作为重构的对照基线。

用法:
    <project-root>\\.venv\\Scripts\\python.exe tests\\smoke.py
    ... --base http://127.0.0.1:8777 --out _refactor\\baseline.json
    ... --strict            # 有任何 FAIL 就 exit 1（CI 用）

设计原则:
  * 只发 GET（外加可选的一次 /api/chat 探活，默认关）——不改数据
  * 不对具体条数做断言（数据会变），只断言「结构」：HTTP 状态 + 顶层字段 + 元素 schema
  * 每次运行把结果写成 JSON 基线，重构前后各跑一次，然后 diff 两份基线
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 检查表：(名称, 路径, 期望状态码, 必须存在的顶层字段, 列表字段名→必须存在于元素里的键) ──
CHECKS: list[tuple[str, str, int, tuple[str, ...], tuple[str, str] | None]] = [
    ("health",        "/api/health",          200, ("ok",),                      None),
    ("status",        "/api/status",          200, ("state",),                   None),
    ("counts",        "/api/counts",          200, (),                           None),
    ("notes",         "/api/notes?limit=5",   200, ("notes",),                   ("notes", "id")),
    ("note_dates",    "/api/note_dates",      200, (),                           None),
    ("search",        "/api/search?q=%E9%87%8F", 200, (),                        None),
    ("todos",         "/api/todos",           200, ("todos",),                   ("todos", "id")),
    ("expenses",      "/api/expenses",        200, (),                           None),
    ("diary_today",   "/api/diary/today",     200, (),                           None),
    ("diary_recent",  "/api/diary/recent",    200, (),                           None),
    ("courses",       "/api/courses",         200, (),                           None),
    ("contacts",      "/api/contacts",        200, (),                           None),
    ("reports",       "/api/reports",         200, (),                           None),
    ("reports_badge", "/api/reports/badge",   200, (),                           None),
    ("digest",        "/api/digest",          200, (),                           None),
    ("categories",    "/api/categories",      200, (),                           None),
    ("config",        "/api/config",          200, (),                           None),
    ("conflicts",     "/api/conflicts",       200, (),                           None),
    ("ollama",        "/api/ollama",          200, (),                           None),
    ("csu_overview",  "/api/csu/overview",    200, (),                           None),
    ("keiwu_status",  "/api/keiwu/status",    200, (),                           None),
    ("panel",         "/",                    200, (),                           None),
    ("ui_panel",      "/ui/panel.html",       200, (),                           None),
    ("ui_app_js",     "/ui/app.js",           200, (),                           None),
    ("ui_modules_js", "/ui/modules.js",       200, (),                           None),
]


def fetch(base: str, path: str, timeout: float = 8.0):
    url = base.rstrip("/") + path
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "luyuan-smoke/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, body, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200], (time.perf_counter() - t0) * 1000
    except Exception as e:  # noqa: BLE001 — 探活要吞掉一切
        return None, str(e).encode()[:200], (time.perf_counter() - t0) * 1000


def check_one(base: str, spec) -> dict:
    name, path, want, keys, list_key = spec
    status, body, ms = fetch(base, path)
    rec = {
        "name": name,
        "path": path,
        "status": status,
        "want": want,
        "ms": round(ms, 1),
        "ok": status == want,
        "detail": "",
        "shape": None,
    }
    if status != want:
        rec["detail"] = body[:160].decode("utf-8", "replace")
        return rec

    ctype = ""
    try:
        payload = json.loads(body.decode("utf-8"))
        ctype = "json"
    except Exception:
        payload = None

    if payload is None:
        rec["shape"] = {"type": "text", "bytes": len(body)}
        return rec

    # 顶层字段 + 元素 schema
    missing = [k for k in keys if k not in payload]
    if missing:
        rec["ok"] = False
        rec["detail"] = f"缺顶层字段: {missing}"
    shape: dict = {"type": "json", "top": sorted(payload.keys()) if isinstance(payload, dict) else "list"}
    if list_key and isinstance(payload, dict):
        arr = payload.get(list_key[0])
        if isinstance(arr, list) and arr:
            shape["elem_keys"] = sorted(arr[0].keys()) if isinstance(arr[0], dict) else str(type(arr[0]))
            shape["count"] = len(arr)
        else:
            shape["count"] = 0
    rec["shape"] = shape
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8777")
    ap.add_argument("--out", default=str(ROOT / "_refactor" / "baseline.json"))
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    try:  # Windows 控制台默认 GBK，中文会乱码
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    print(f"路远冒烟 · base={args.base} · {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("-" * 78)

    results = [check_one(args.base, spec) for spec in CHECKS]
    fails = [r for r in results if not r["ok"]]

    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        extra = ""
        if r["shape"] and r["shape"].get("count") is not None:
            extra = f" n={r['shape']['count']}"
        print(f"  [{flag}] {r['name']:<14} {r['status']!s:<5} {r['ms']:>7.1f}ms{extra}"
              + (f"  ← {r['detail']}" if r["detail"] else ""))

    print("-" * 78)
    print(f"共 {len(results)} 项，通过 {len(results) - len(fails)}，失败 {len(fails)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "base": args.base,
        "total": len(results),
        "failed": len(fails),
        "results": results,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"基线已写入 {out}")

    return 1 if (fails and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
