# -*- coding: utf-8 -*-
"""A8 冲突二选一接口验收（2026-09-14）：列对 / 本体为准 / 副本为准 / 孤儿收养 / 隔离区不物理删。
8778 隔离实例 + 全临时数据。"""
import sys
import os
import json
import time
import tempfile
import threading
import urllib.request
import urllib.error

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_conflict_")

import conflicts

NOTES = os.path.join(tmp, "notes")
TRASH = os.path.join(tmp, "conflict_trash")
conflicts._SCAN_DIRS = [NOTES]
conflicts._TRASH = TRASH
os.makedirs(NOTES, exist_ok=True)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


def put(fname, obj):
    with open(os.path.join(NOTES, fname), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read(fname):
    try:
        with open(os.path.join(NOTES, fname), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ① 成对：本体 + 冲突副本（同一条笔记双端改）
put("2026-09-14_10-00-00_ab12cd34.json",
    {"id": "ab12cd34", "text": "电脑版正文", "created_at": "2026-09-14T10:00:00"})
put("2026-09-14_10-00-00_ab12cd34.sync-conflict-20260914-101010.json",
    {"id": "ab12cd34", "text": "手机版正文", "created_at": "2026-09-14T10:00:00"})
# ② 孤儿：只有冲突副本（本体被改名/已删）
put("note_orphan.json.sync-conflict-20260914-111111.json",
    {"id": "orphan01", "text": "孤儿正文"})
# ③ 联系人子目录的冲突（实际不会发生在这测试里，扫范围单目录即可）

import server
import uvicorn


def _serve():
    uvicorn.run(server.app, host="127.0.0.1", port=8778, log_level="warning")


threading.Thread(target=_serve, daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen("http://127.0.0.1:8778/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.2)


def api(path, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:8778" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


BASE = "2026-09-14_10-00-00_ab12cd34.json"
CONF = BASE.replace(".json", "") + ".sync-conflict-20260914-101010.json"

# 1) 列表：一对 + 一孤儿，带左右对照 JSON
st, r = api("/api/conflicts")
items = r.get("conflicts", [])
check("列表 200 两条", st == 200 and len(items) == 2, str(r)[:120])
pair = next((x for x in items if x.get("conflict") == CONF), {})
check("成对条目带 base+双 JSON 对照", pair.get("base") == BASE
      and (pair.get("base_json") or {}).get("text") == "电脑版正文"
      and (pair.get("conflict_json") or {}).get("text") == "手机版正文", str(pair)[:200])
orp = next((x for x in items if x.get("orphan")), {})
check("孤儿条目标记 orphan", orp.get("orphan") is True and orp.get("base") is None, str(orp)[:150])

# 2) 本体为准 → 副本进隔离区，本体不动
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": CONF, "keep": "base"})
check("keep=base 200", st == 200 and r.get("kept") == BASE, str(r))
check("副本已离开同步目录", not os.path.exists(os.path.join(NOTES, CONF)), "")
check("本体内容未被改动", read(BASE)["text"] == "电脑版正文", "")
trashed = os.listdir(TRASH) if os.path.isdir(TRASH) else []
check("败者进隔离区（未物理删）", len(trashed) == 1 and trashed[0].endswith(".json"), str(trashed))

# 3) 副本为准 → 副本内容写回本体名，旧本体进隔离区
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": CONF, "keep": "conflict"})
check("keep=conflict 200（副本已删→应为400）", st == 400, str((st, r)))  # 上一步副本已被隔离，这次必 400
put(CONF, {"id": "ab12cd34", "text": "手机版正文2", "created_at": "2026-09-14T10:00:00"})
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": CONF, "keep": "conflict"})
check("keep=conflict 200", st == 200 and r.get("kept") == BASE, str(r))
check("副本内容写回本体名", read(BASE)["text"] == "手机版正文2", str(read(BASE)))
check("旧本体进隔离区", len(os.listdir(TRASH)) == 2, str(os.listdir(TRASH)))

# 4) 孤儿收养：keep=conflict → 转正为本体名
st, r = api("/api/conflicts/resolve", method="POST",
            body={"conflict": "note_orphan.json.sync-conflict-20260914-111111.json",
                  "keep": "conflict"})
check("孤儿收养 200", st == 200 and r.get("kept") == "note_orphan.json", str(r))
check("收养后本体存在", read("note_orphan.json")["text"] == "孤儿正文", "")

# 5) 参数防线
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": CONF, "keep": "wat"})
check("非法 keep 400", st == 400, str(st))
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": "不存在.json", "keep": "base"})
check("不存在冲突 400", st == 400, str(st))
# 6) 孤儿隔离丢弃（keep=discard 仅孤儿可用；成对冲突 discard 必 400）
put("note_drop.json.sync-conflict-20260914-121212.json", {"id": "drop01", "text": "待丢弃孤儿"})
put(BASE, {"id": "ab12cd34", "text": "成对本体", "created_at": "2026-09-14T10:00:00"})
put(CONF, {"id": "ab12cd34", "text": "成对副本", "created_at": "2026-09-14T10:00:00"})
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": CONF, "keep": "discard"})
check("成对冲突 discard 400", st == 400, str(st))
st, r = api("/api/conflicts/resolve", method="POST",
            body={"conflict": "note_drop.json.sync-conflict-20260914-121212.json", "keep": "discard"})
check("孤儿 discard 200", st == 200 and r.get("quarantined") == "note_drop.json.sync-conflict-20260914-121212.json", str(r))
check("孤儿已离开同步目录", not os.path.exists(os.path.join(NOTES, "note_drop.json.sync-conflict-20260914-121212.json")), "")
st, r = api("/api/conflicts/resolve", method="POST", body={"conflict": CONF, "keep": "base"})
check("清理成对冲突(keep=base)", st == 200, str((st, r)))
st, r = api("/api/conflicts")
check("裁决后列表清空", r.get("conflicts") == [], str(r)[:100])

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)
