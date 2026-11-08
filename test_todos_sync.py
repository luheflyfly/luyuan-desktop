# -*- coding: utf-8 -*-
"""P-todo 后端验收（2026-09-14）：todo_<id8>.json 读取 + 完成/丢弃回写 + kind 实体不进笔记流。
8778 隔离实例 + 全临时数据（SYNC_FORMAT v3 §10.4 契约）。"""
import sys
import os
import json
import time
import tempfile
import threading
import datetime
import urllib.request
import urllib.error

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_ptodo_")

import store
import todos
import classify

store._cfg_cache = {"notes_dir": tmp}
todos._DIR = tmp
classify.process_async = lambda *a, **k: None

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


now_iso = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def put(fname, obj):
    with open(os.path.join(tmp, fname), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# 种子：①手机端确认后落盘的待办（契约全字段）②普通笔记③未知 kind（带 text！）④冲突副本
T1 = {"kind": "todo", "id": "11111111-aaaa-bbbb-cccc-111111111111", "schema": 3,
      "device": "phone", "deleted": False,
      "text": "明天下午三点要交材料", "who": "张三", "when_text": "明天下午三点",
      "raw": "明天下午三点提醒我交材料", "source": "wechat", "sender": "张三",
      "done": False, "done_at": None,
      "created_at": now_iso, "updated_at": now_iso}
put("todo_11111111.json", T1)
put("todo_22222222.json", dict(T1, id="22222222-bbbb-cccc-dddd-222222222222",
                               text="周五前买火车票", raw="周五前记得买火车票"))
put("todo_33333333.sync-conflict-20260914-000000.json", dict(T1, id="33333333"))
put("blob_44444444.json", {"kind": "blob", "id": "44444444", "text": "未知kind带text不该出现在任何列表",
                           "created_at": now_iso})
store.add_note("普通笔记一条，别被待办挤掉", source="pc")

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


# 1) 列表：契约字段原样、冲突副本与未知 kind 不出现
st, r = api("/api/todos")
check("GET /api/todos 200", st == 200, str(st))
check("count=2（冲突副本不算）", r.get("count") == 2, str(r)[:120])
t1 = next((t for t in r.get("todos", []) if t.get("id", "").startswith("11111111")), {})
check("契约字段原样保留", all(t1.get(k) == T1[k] for k in
                          ("text", "who", "when_text", "raw", "source", "sender")), str(t1)[:150])

# 2) todo/未知kind 不进笔记流（kind 排除守卫——P-todo 最关键的洞）
st, r = api("/api/notes?limit=200")
texts = [n.get("text", "") for n in r.get("notes", [])]
check("todo 不出现在笔记列表", not any("交材料" in t for t in texts), str(texts)[:120])
check("未知 kind 不出现在笔记列表", not any("未知kind" in t for t in texts), str(texts)[:120])
check("普通笔记还在", any("普通笔记一条" in t for t in texts), str(texts)[:120])
st, r = api("/api/counts")
check("counts.note 只算真笔记", r.get("note") == 1, str(r))
check("counts.msg_todo=2", r.get("msg_todo") == 2, str(r))
dates = store.note_dates()
today = datetime.date.today().isoformat()
check("note_dates 不给 todo 计数", dates and dates[0]["date"] == today and dates[0]["count"] == 1,
      str(dates[:2]))

# 3) 完成：回写 done/done_at，且真的落在磁盘文件（Syncthing 带回手机）
st, r = api("/api/todos/11111111-aaaa-bbbb-cccc-111111111111/done", method="POST")
check("POST done 200", st == 200, "%s %s" % (st, str(r)[:80]))
check("done=true + done_at ISO", r.get("todo", {}).get("done") is True
      and str(r.get("todo", {}).get("done_at", "")).startswith(today), str(r)[:150])
with open(os.path.join(tmp, "todo_11111111.json"), encoding="utf-8") as f:
    disk = json.load(f)
check("回写落盘（done/done_at/updated_at）", disk["done"] is True and disk["done_at"]
      and disk["updated_at"], str(disk)[:150])
st, r = api("/api/todos")
check("完成后 count=1 且进 done_today", r.get("count") == 1 and len(r.get("done_today", [])) == 1,
      str(r)[:150])

# 4) 丢弃：文件物理删除（与手机端 ✗不要 同行为）
st, r = api("/api/todos/22222222-bbbb-cccc-dddd-222222222222/discard", method="POST")
check("discard 200 deleted=true", st == 200 and r.get("deleted") is True, str(r))
check("磁盘文件已删", not os.path.exists(os.path.join(tmp, "todo_22222222.json")), "")
st, r = api("/api/todos/deadbeef/done", method="POST")
check("不存在的 id 404", st == 404, str(st))

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)
