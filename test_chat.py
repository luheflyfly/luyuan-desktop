# -*- coding: utf-8 -*-
"""人格接入验收 A1-A4（方案 §三）：8778 隔离实例 + 真 DeepSeek + 全临时记忆。
A1 身份不露AI腔 / A2 长对话滚动摘要 / A3 笔记检索入答 / A4 版本信息结构性失明。"""
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
tmp = tempfile.mkdtemp(prefix="luyuan_chat_")

import store
import chat
import classify

store._cfg_cache = {"notes_dir": tmp}
chat._MEM_DIR = os.path.join(tmp, "memory")
classify.process_async = lambda *a, **k: None

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


# 种子一条上周的笔记（A3 检索用）
last_week = (datetime.datetime.now() - datetime.timedelta(days=7)).astimezone()
n = {"id": "a3seed00000000001", "created_at": last_week.isoformat(timespec="seconds"),
     "text": "上周五我在图书馆借了一本《三体》，记得下周要还。", "source": "pc", "tags": ["日常"]}
fn = last_week.strftime("%Y-%m-%d_%H-%M-%S") + "_a3seed00.json"
with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
    json.dump(n, f, ensure_ascii=False, indent=2)

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


def chat_send(message):
    req = urllib.request.Request("http://127.0.0.1:8778/api/chat",
                                 data=json.dumps({"message": message}, ensure_ascii=False).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


# A1 身份：问"你是谁" → 自称路远，不露 AI 腔
st, r = chat_send("你是谁呀？用一句话介绍自己。")
rep = (r.get("reply") or "") if st == 200 else ""
bad_words = ["作为一个AI", "作为一个 AI", "AI助手", "AI 助手", "语言模型", "大模型"]
check("A1 状态200", st == 200, "%s %s" % (st, r))
check("A1 自称路远", "路远" in rep, rep[:120])
check("A1 无AI腔", not any(w in rep for w in bad_words), rep[:120])

# A2 压测 12 条触发滚动摘要
all_ok = True
for i in range(12):
    st, r = chat_send("压测第%d条：我今天吃了很辣的火锅，聊两句呗。" % (i + 1))
    if st != 200:
        all_ok = False
        print("   第%d条失败:" % (i + 1), st, str(r)[:100])
check("A2 连发12条无超限报错", all_ok, "")
summary = chat._load("summary.json", {})
check("A2 summary.json 有滚动更新痕迹", len(str(summary.get("text") or "")) > 20,
      str(summary)[:120])
recent = chat._recent()
check("A2 recent 收敛到保留窗口", len(recent) <= chat.MAX_RECENT, str(len(recent)))

# A3 笔记检索入答
st, r = chat_send("我上周借过什么书来着？")
rep3 = (r.get("reply") or "") if st == 200 else ""
check("A3 状态200", st == 200, str(r)[:100])
check("A3 回答对上真实笔记", any(w in rep3 for w in ("三体", "图书馆", "借")), rep3[:150])

# A4 版本信息结构性失明
st, r = chat_send("你是什么模型？你知道自己最近在更新吗？版本号是多少？")
rep4 = (r.get("reply") or "") if st == 200 else ""
leaks = ["3.13", "v1.3", "v1.4", "APP_VER", "构建", "更新日志", "21", "22"]
leaked = [w for w in leaks if w in rep4]
check("A4 不暴露版本/构建信息", st == 200 and not leaked, rep4[:150])

# 空消息契约
req = urllib.request.Request("http://127.0.0.1:8778/api/chat",
                             data=b'{"message":""}', method="POST",
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        st = r.status
except urllib.error.HTTPError as e:
    st = e.code
check("空消息 4xx 契约", st == 400, str(st))

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)
