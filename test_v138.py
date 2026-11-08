# -*- coding: utf-8 -*-
"""v1.38 稍后读隔离活体测试：全临时数据 + 真实网络抓取（example.com）。
覆盖：normalize_url、剪贴板手动通道、自动认领、真抓取写回、去重、
非网址不碰、失败重试进 failed、pending_items 统计。"""
import sys
import os
import json
import time
import tempfile
import logging

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_t138_")

import store
import readlater
import classify

store._cfg_cache = {"notes_dir": tmp}
classify.process_async = lambda *a, **k: None

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


# normalize_url
check("纯网址通过", readlater.normalize_url(
    "https://mp.weixin.qq.com/s/abc123。") == "https://mp.weixin.qq.com/s/abc123",
    readlater.normalize_url("https://mp.weixin.qq.com/s/abc123。"))
check("非网址拒绝", readlater.normalize_url("密码: abc123") is None, "")
check("密码式内容拒绝", readlater.normalize_url("my password is https") is None, "")
check("超长拒绝", readlater.normalize_url("https://a.com/" + "x" * 3000) is None, "")

# 剪贴板手动通道（monkeypatch 剪贴板内容）
notices = []
readlater.get_clipboard_text = lambda: "https://example.com/"
n = readlater.save_from_clipboard(manual=True,
                                  notify=lambda t, nid: notices.append((t, nid)))
check("手动收网址→建卡", n is not None and n.get("rl_state") == "pending",
      str(n)[:150])
check("去重：同网址不重收", readlater.save_from_clipboard(
    manual=True, notify=lambda t, nid: notices.append((t, nid)))["id"] == n["id"]
    and len([x for x in store.list_notes() if "稍后读" in x["tags"]]) == 1, "")

# 等真抓取线程完成（example.com 很小）
for _ in range(40):
    time.sleep(0.5)
    n2 = store.get_note(n["id"])
    if n2 and n2.get("rl_state") == "done":
        break
check("真抓取 example.com 成功", n2 and n2["rl_state"] == "done",
      str((n2 or {}).get("rl_state")))
check("正文含 Example Domain", "Example Domain" in (n2 or {}).get("text", ""),
      (n2 or {}).get("text", "")[:80])
check("标题/链接字段在位", (n2 or {}).get("link", "").startswith("https://")
      and (n2 or {}).get("rl_title"), "")

# 非网址剪贴板不碰
readlater.get_clipboard_text = lambda: "随便复制的文字不是网址"
n3 = readlater.save_from_clipboard(manual=False,
                                   notify=lambda t, nid: notices.append((t, nid)))
check("非网址剪贴板零动作", n3 is None, str(n3))

# 失败重试 → failed（打不通的地址；清退避时间戳手动推轮加速）
readlater.get_clipboard_text = lambda: "http://127.0.0.1:1/nowhere"
n4 = readlater.save_from_clipboard(manual=True,
                                   notify=lambda t, nid: notices.append((t, nid)))
n5 = None
for _ in range(80):
    time.sleep(0.3)
    n5 = store.get_note(n4["id"])
    if n5 and n5.get("rl_state") == "failed":
        break
    readlater._NEXT_TRY[n4["id"]] = 0
    readlater._FETCHING.pop(n4["id"], None)
    readlater._process_pending()
check("失败3次→failed", n5 and n5["rl_state"] == "failed"
      and n5.get("rl_retry", 0) >= 3, str((n5 or {}).get("rl_retry")))
check("failed 笔记正文=裸网址保留", (n5 or {}).get("text", "").startswith("http"),
      (n5 or {}).get("text", "")[:50])

# 旧式「稍后读裸网址笔记」自动认领（终端/手机分享造出来的）
n6 = store.add_note("http://example.com/", source="pc",
                    tags=["稍后读"])
found = readlater._claim_pending()
check("裸网址旧笔记被认领", any(nid == n6["id"] for nid, _ in found), str(found))
readlater._FETCHING.pop(n6["id"], None)
readlater._process_pending()
for _ in range(40):
    time.sleep(0.5)
    n7 = store.get_note(n6["id"])
    if n7 and n7.get("rl_state") == "done":
        break
check("认领后自动抓完", n7 and n7["rl_state"] == "done",
      str((n7 or {}).get("rl_state")))

# pending_items 统计
st = readlater.pending_items()
check("统计接口", st["done"] == 2 and not st["pending"] and len(st["failed"]) == 1,
      str(st))

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)
