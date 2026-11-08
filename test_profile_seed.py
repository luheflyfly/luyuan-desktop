# -*- coding: utf-8 -*-
"""A6 验收（2026-09-14）：profile.json 自动种子生成 + 改文件即换人格 + 坏文件兜底。
隔离实例跑不了云就不花钱——build_messages 是 /api/chat 组装人设的真实入口，直接断言它的产出。"""
import sys
import os
import json
import tempfile

sys.path.insert(0, r"D:\Luyuan")
import chat

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


tmp = tempfile.mkdtemp(prefix="luyuan_profile_")
chat._MEM_DIR = os.path.join(tmp, "memory")
chat._PROFILE_READY = False

# 1) 首次访问 → profile.json 自动生成，内容 = 内置人设
msgs = chat.build_messages("在吗")
pf = os.path.join(chat._MEM_DIR, "profile.json")
exists = os.path.exists(pf)
check("首次访问自动生成 profile.json", exists, pf)
if exists:
    with open(pf, "r", encoding="utf-8") as f:
        seed = json.load(f)
    check("种子人设 = _DEFAULT_PROFILE", seed.get("persona") == chat._DEFAULT_PROFILE["persona"],
          str(seed.get("persona"))[:60])
    check("system 提示含内置人设", chat._DEFAULT_PROFILE["persona"][:20] in msgs[0]["content"],
          msgs[0]["content"][:60])

# 2) 改文件即换人格（不动代码、不重启）
chat._PROFILE_READY = False
marker = "你叫测试人格甲，说话像老水手。"
with open(pf, "w", encoding="utf-8") as f:
    json.dump({"persona": marker, "facts": ["阿河喜欢熬夜"]}, f, ensure_ascii=False)
msgs2 = chat.build_messages("在吗")
check("改 profile.json 后人设生效", marker in msgs2[0]["content"], msgs2[0]["content"][:60])
check("facts 也进 system", "阿河喜欢熬夜" in msgs2[0]["content"], msgs2[0]["content"][:100])

# 3) 坏文件不炸，兜底回内置人设
chat._PROFILE_READY = False
with open(pf, "w", encoding="utf-8") as f:
    f.write("{bad json")
msgs3 = chat.build_messages("在吗")
check("坏 profile.json 兜底内置人设", chat._DEFAULT_PROFILE["persona"][:20] in msgs3[0]["content"],
      msgs3[0]["content"][:60])

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)
