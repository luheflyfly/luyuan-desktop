# -*- coding: utf-8 -*-
"""微信回复指令解析回归（配合 test_v137.py / test_chat.py 一起跑）。

覆盖 2026-09-13 用户实测踩坑：「回一下路平坦成河说我下午有事」只存成待办、没真发微信。
根因是旧正则只认「回X：正文」，衬词「一下」与引导语「说」都没处理。

用法：cd <project-root> && ./.venv/Scripts/python.exe test_wechat_parse.py

🔴 安全铁律：名字必须有明确边界（标点 / 引导语「说·告诉·讲」/ 本身是已存联系人）。
没边界时宁可判「不是微信指令」落笔记，也**绝不猜名字**——猜错 = Ctrl+F 搜错人 = 消息发错人。
所以下面 MISS 表里的用例必须全部为 None，改解析逻辑时一条都不许松。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import router  # noqa: E402

# (输入, 期望 to, 期望正文)   to='current'/'last' 为代词/最近聊天
HIT = [
    ("回他：书在图书馆三楼", "current", "书在图书馆三楼"),
    ("回他一下，书在图书馆三楼", "current", "书在图书馆三楼"),
    ("回复张三：好的收到，两点见", "张三", "好的收到，两点见"),
    ("回一下张三说我下午去找他", "张三", "我下午去找他"),          # ← 用户实际说法
    ("回复张三说下午两点来领书", "张三", "下午两点来领书"),
    ("回复张三，说下午两点来领书", "张三", "下午两点来领书"),
    ("回复张三，告诉他下午来找我", "张三", "下午来找我"),
    ("回复张三跟他说下午来找我", "张三", "下午来找我"),
    ("回一下张三：我下午有事", "张三", "我下午有事"),
    ("回刚才那个：收到了", "last", "收到了"),
    ("回复未读：稍等我看看", "last", "稍等我看看"),
    ("发给李四一下：明天见", "李四", "明天见"),
    ("回他：说好的下午三点", "current", "说好的下午三点"),        # 正文里的「说」不能被吃掉
    ("回复张三：说好的下午三点", "张三", "说好的下午三点"),      # 冒号=正文分隔，不剥「说」
    # ---- 2026-09-13 15:58 用户实测再踩：动词用了「给」----
    ("给路平坦成河说我下午要去图书馆", "路平坦成河", "我下午要去图书馆"),  # ← 用户实际说法
    ("跟路平坦成河说我下午要去图书馆", "路平坦成河", "我下午要去图书馆"),
    ("帮路平坦成河说下午不用等我", "路平坦成河", "下午不用等我"),
    ("给路平坦成河：我下午要去图书馆", "路平坦成河", "我下午要去图书馆"),
    ("给他说下午有事", "current", "下午有事"),
    ("给刚才那个说收到了", "last", "收到了"),
    # ---- 衬词「一下」是分隔符、不是正文；「一下午」是时间词，别被剥 ----
    ("给路平坦成河说一下我下午要去图书馆", "路平坦成河", "我下午要去图书馆"),
    ("回他一下午开会", "current", "一下午开会"),
    # ---- 09-14 夜：「路平坦成河」已建为联系人（微信测试小号），⑤通道命中已存
    #      联系人是设计行为——本条原在 MISS 表（当时它还不是联系人，期望 None），
    #      前提已过时，移入 HIT。「不猜名字」铁律不变：⑤只认已存联系人前缀。----
    ("回一下路平坦成河我下午有事", "路平坦成河", "我下午有事"),
]

# 必须解析失败（落笔记）——防「消息发错人 / 把日常句当发微信」
MISS = [
    "回复邮件",
    "回复邮件：今天处理完了",
    "回学校明天开会",
    "回他",
    "回复张三",
    "回复路平坦成河：",              # 有名字没正文 → 落笔记，绝不瞎猜
    "回复一下",
    "今天晚上吃什么",
    # （原「回一下路平坦成河我下午有事」已移 HIT：该名字现在是联系人，见 HIT 表末）
    # ---- 弱动词（给/跟/帮/替）在日常句里极常见，必须一条都不许中 ----
    "给妈妈买药",
    "给车加油",
    "给手机充电",
    "给老师交作业",
    "给同学还书",
    "跟老师请假",
    "帮他带早餐",
    "给她打电话",
    "给他发个红包",
    "给老师说一声",                  # 引导语后只剩衬词 → 没正文，不发
    "给张三说一下",
]


# 本地模型通道（需要 Ollama 在线；离线自动跳过）
# 覆盖「正则追不上」的口语变体：动词不是「回/发」，语序反过来，靠「让X知道」这类说法。
LLM_HIT = [
    ("给路平坦成河说我下午要去图书馆", ("路平坦成河", "我下午要去图书馆")),
    ("帮我跟他说一声我晚点到", ("current", "我晚点到")),
    ("跟刚才那个说收到了", ("last", "收到了")),
    ("让路平坦成河知道明天不用等我", ("路平坦成河", "明天不用等我")),
    ("路平坦成河那边回一句说我马上到", ("路平坦成河", "我马上到")),
]

# 模型也不许误判成发消息（日常句 / 纯笔记）
LLM_MISS = [
    ("给妈妈买药", None),
    ("跟老师请假", None),
    ("给车加油", None),
    ("明天下午三点开会", None),
    ("买两本书 58块", None),
]


def _run_llm():
    """模型通道回归。Ollama 离线 → 打印 SKIP 返回 0（不阻塞回归）。"""
    try:
        import smart
        if not smart.ollama_running():
            print("SKIP LLM 通道：Ollama 没在跑（没测，不算失败）")
            return 0
    except Exception as e:
        print("SKIP LLM 通道：%s" % e)
        return 0
    bad = 0
    for text, want in LLM_HIT + LLM_MISS:
        got = router._llm_wechat_judge(text)
        ok = got == want
        bad += 0 if ok else 1
        print("%s [llm] %-24s -> %r (期望 %r)" % ("OK " if ok else "FAIL", text, got, want))
    return bad


def main():
    bad = 0
    for text, want_to, want_body in HIT:
        got = router.parse_wechat(text)
        ok = got == (want_to, want_body)
        bad += 0 if ok else 1
        print("%s %-26s -> %r" % ("OK " if ok else "FAIL", text, got))
    print("-" * 62)
    for text in MISS:
        got = router.parse_wechat(text)
        ok = got is None
        bad += 0 if ok else 1
        print("%s %-26s -> %r" % ("OK " if ok else "FAIL", text, got))
    total = len(HIT) + len(MISS)
    print("-" * 62)
    print("正则通道 %d/%d PASS" % (total - bad, total))
    llm_bad = _run_llm()
    print("-" * 62)
    print("总计 %d/%d PASS%s" % (total - bad, total,
                                 "" if not llm_bad else "（LLM 通道 %d 条挂）" % llm_bad))
    return 1 if (bad or llm_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
