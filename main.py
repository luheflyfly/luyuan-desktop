"""路远 v1 主程序：系统托盘 + 全局热键 + 唤醒词 + 悬浮窗 + Web 面板。
双击 launch.bat（或开机自启）即可运行；不依赖任何 agent。
"""
import os
import sys
import time
import webbrowser
import threading
import logging
import queue
import socket
import json
import subprocess
import atexit

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config
import store
import stt
import recorder
import bridge

os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
logging.basicConfig(
    filename=os.path.join(BASE, "data", "luyuan.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("luyuan")

icon = None
_capture_lock = threading.Lock()
# ── 桌面壳模式（2026-10-30）：壳进程负责窗口/托盘，本进程只当后台大脑。
#    由 desktop/shell.py 以 `main.py --headless` 拉起；不带这个开关时行为与旧版完全一致。
HEADLESS = ("--headless" in sys.argv) or (os.environ.get("LUYUAN_HEADLESS") == "1")
SHELL_CTRL = "http://127.0.0.1:8781"

ww_stop = threading.Event()
_server_proc = None  # 独立运行的 Web 服务子进程（与 GUI 解耦，崩一个不拖另一个）
_browser_opened = False  # 启动期浏览器是否已自动开过（防托盘路径二次开重复标签页）


def _shell_show(nid=""):
    """通知桌面壳把窗口显示出来（壳没在跑 → 返回 False，调用方回退浏览器）。"""
    try:
        import urllib.request
        q = ("?nid=" + str(nid)) if nid else ""
        urllib.request.urlopen(SHELL_CTRL + "/show" + q, timeout=1.2).read()
        return True
    except Exception:
        return False


def open_browser(nid=""):
    """打开面板：桌面壳在跑就唤起壳窗口；否则回退系统默认浏览器（老路径保底）。"""
    global _browser_opened
    if HEADLESS or _shell_show(nid):
        _browser_opened = True
        return
    cfg = config.load()["server"]
    url = f"http://127.0.0.1:{cfg['port']}/"
    if nid:
        url += f"#n={nid}"
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)
        else:
            webbrowser.open(url)
    except Exception:
        try:
            webbrowser.open(url)
        except Exception:
            pass


def _open_browser_when_ready():
    """启动期专用：服务端口一通就自动开面板，不再等托盘创建完。
    优化（2026-09-11）：原先浏览器要等托盘图标就绪才开（托盘排在最后，
    白等 ~2s）；现在 Web 服务一起来面板就弹出，托盘稍后到位不影响。
    用户手动点菜单/热键打开时不受 _browser_opened 限制。"""
    global _browser_opened
    cfg = config.load()["server"]
    port = cfg["port"]
    import socket as _sock
    for _ in range(200):        # 最多等 40s（0.2s 一轮），正常 ~4s 内就通
        s = _sock.socket()
        s.settimeout(0.4)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
        except OSError:
            time.sleep(0.2)
            continue
        _browser_opened = True
        open_browser()
        log.info("面板端口就绪，已自动打开浏览器")
        return
    log.warning("启动期面板端口 40s 未就绪，放弃自动开浏览器（托盘路径仍可手动开）")


def toggle_capture():
    """热键回调：聆听中 / 识别中则停止，否则开始。"""
    st = bridge.get_status().get("state")
    if st in ("listening", "transcribing"):
        bridge.request_stop()
    else:
        bridge.request_capture()


# ---------------- 录音指示窗（独立 tkinter 进程；录音+转写期间常驻，结束即消失） ----------------
NOTIFY_PORT = 8779
_notifier_proc = None


def _send_notify(msg):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", NOTIFY_PORT))
        s.close()
    except Exception:
        pass


_gui_py_cache = None


def find_gui_python():
    """找一个带 tkinter 的 Python（优先系统 Python 3.14）。结果缓存。"""
    global _gui_py_cache
    if _gui_py_cache:
        return _gui_py_cache
    import shutil
    launcher = shutil.which("py")
    base = os.path.expanduser("~")
    prefixes = []
    if launcher:
        prefixes.append([launcher, "-3.14"])
    prefixes.append([os.path.join(base, "AppData", "Local", "Python",
                                  "pythoncore-3.14-64", "python.exe")])
    prefixes.append([os.path.join(base, "AppData", "Local", "Microsoft",
                                  "WindowsApps", "python3.exe")])
    if launcher:
        prefixes.append([launcher, "-3"])
    for pre in prefixes:
        exe = pre[0]
        if not os.path.isfile(exe):
            continue
        try:
            r = subprocess.run(pre + ["-c", "import tkinter"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                _gui_py_cache = pre
                return pre
        except Exception:
            continue
    return None


def _kill_luyuan_py(name):
    r"""杀掉所有 cmdline 含 D:\Luyuan\<name> 的 python 进程（精确路径，不误伤别项目）。"""
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*<project-root>\\%s*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % name)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       stderr=subprocess.DEVNULL, timeout=15)
        time.sleep(0.8)
    except Exception:
        pass


def ensure_notifier():
    """启动指示窗进程。先清掉旧实例再拉新的——旧版"8779 被占就收编"会收进
    上个主程序留下的孤儿（同天禧键失灵同款问题）。"""
    global _notifier_proc
    _kill_luyuan_py("notifier.py")
    pre = find_gui_python()
    if not pre:
        log.warning("未找到带 tkinter 的 Python，录音指示窗不可用（原生通知仍有效）")
        return
    try:
        _notifier_proc = subprocess.Popen(
            pre + [os.path.join(BASE, "notifier.py")],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log.info("notifier fresh process started")
    except Exception as e:
        log.warning("启动指示窗失败：%s", e)


def stop_notifier():
    """退出时无论指示窗是不是本会话拉起的，都广播 quit，杜绝孤儿窗口。"""
    try:
        _send_notify({"kind": "quit"})
    except Exception:
        pass
    if _notifier_proc is None:
        return
    try:
        _notifier_proc.terminate()
    except Exception:
        pass


class NotifierClient:
    def _route(self, msg):
        """录音指示优先走 pywebview 悬浮层；不在时回退 tkinter 通知器。"""
        if _overlay_ok():
            _qn_send(msg)
        else:
            _send_notify(msg)

    def show(self, title, body="", ms=3000):
        if _overlay_ok():
            return   # 悬浮层模式下不再弹 tkinter toast
        _send_notify({"kind": "toast", "title": title, "body": body, "ms": ms})

    def rec_start(self, title="聆听中", body=""):
        self._route({"kind": "rec_start", "title": title, "body": body})

    def rec_phase(self, title="识别中…"):
        self._route({"kind": "rec_phase", "title": title})

    def rec_stop(self, title="", body=""):
        self._route({"kind": "rec_stop", "title": title, "body": body})

    def hide(self):
        self._route({"kind": "hide"})


notifier = NotifierClient()


# ---------------- 桌面通知（Windows 原生 Toast） ----------------
def panel_url(nid=""):
    try:
        port = config.load()["server"].get("port", 8777)
    except Exception:
        port = 8777
    return "http://127.0.0.1:%s/#n=%s" % (port, nid) if nid \
        else "http://127.0.0.1:%s/" % port


def native_toast(title, body="", ms=5000, launch="", actions=None):
    """Windows 原生通知。失败回退托盘气泡。"""
    import toast

    def _balloon(t, b, m):
        try:
            if icon is not None:
                icon.notify(b or t, "路远")
        except Exception:
            pass

    return toast.native_toast(title, body, launch=launch, actions=actions,
                              ms=ms, fallback=_balloon)


# ---------------- 捕获流水线 ----------------
def do_capture():
    if not _capture_lock.acquire(blocking=False):
        native_toast("⏳ 正在记录中，请稍候…")
        return
    try:
        cfg = config.load()
        cap = cfg.get("capture", {})
        bridge.clear_stop()
        # 刚被唤醒词触发时，先压一个短静默，避免同一句话被重复触发
        bridge.set_ww_cooldown(1.0)
        if _overlay_ok():
            notifier.rec_start("聆听中", "说完按 F10 结束")
        else:
            native_toast("🎤 开始录音", "说完再按 F10 结束")
        bridge.set_status("listening")
        log.info("capture started (state=listening)")
        wav = os.path.join(BASE, "temp_rec.wav")
        try:
            recorder.record_until_stop(
                wav,
                bridge.get_stop_event(),
                samplerate=int(cfg.get("samplerate", 16000)),
                max_seconds=cap.get("manual_max_seconds", 120),
            )
        except Exception as e:
            notifier.rec_stop()
            native_toast("⚠️ 麦克风出错", str(e))
            bridge.set_status("idle", error=f"麦克风出错：{e}")
            time.sleep(2.5)
            return

        notifier.rec_phase("识别中…")   # 同一个窗改文字：录音停了但还在处理
        bridge.set_status("transcribing")
        try:
            text, raw_text = stt.transcribe(wav, return_raw=True)
        except Exception as e:
            notifier.rec_stop()
            native_toast("⚠️ 识别失败", str(e))
            bridge.set_status("idle", error=f"识别失败：{e}")
            time.sleep(2.5)
            return

        if text.strip():
            # 先判是不是「回微信」指令（零触控语音回消息，Stage 1）
            try:
                import router
                # 🔴 09-14：必须走 resolved 入口——同音纠正（张俊扬→张俊杨）只在
                #    parse_wechat_resolved 里，绕过它语音路径会把 STT 错名原样发给
                #    微信搜索（与 router 内部路径不同步）。
                wcmd = router.parse_wechat_resolved(text)
            except Exception:
                wcmd = None
            if wcmd is not None:
                to, body = wcmd
                import wechat
                cfg = config.load().get("wechat", {})
                res = wechat.send_reply(to, body, cfg)
                try:
                    note = store.add_note(
                        "→%s：%s" % (
                            ("当前聊天" if to in ("current", "last") else to), body),
                        source="wechat", tags=["微信回复"])
                except Exception:
                    note = None
                notifier.rec_stop()
                ok = res.get("sent")
                native_toast("✅ 已发微信" if ok else "📋 微信回复已备好",
                             (res.get("label") or body)[:80],
                             launch=panel_url(note["id"]) if note else panel_url(),
                             actions=[("📋 打开面板",
                                       panel_url(note["id"]) if note else panel_url())])
                bridge.set_status("wechat_sent", text)
                log.info("wechat reply: to=%s sent=%s", to, ok)
            else:
                note = store.add_note(text, extra={"raw_text": raw_text})
                notifier.rec_stop()
                native_toast("✅ 已记录", text[:80],
                             launch=panel_url(note["id"]) if note else panel_url(),
                             actions=[("📋 打开面板", panel_url(note["id"]) if note else panel_url())])
                bridge.set_status("saved", text)
                # 自动归类（后台线程，失败静默，绝不影响记事）
                if note:
                    try:
                        import classify
                        classify.classify_async(note["id"], text)
                    except Exception:
                        pass
        else:
            notifier.rec_stop()
            native_toast("🤔 没听清", "再试一次：离麦近一点，说完整句")
            time.sleep(1.5)
        bridge.set_status("idle")
    finally:
        # 录制结束后给一段静默冷却期，避免刚说的话里含"路远"被立刻再触发
        bridge.set_ww_cooldown(4.0)
        _capture_lock.release()


# ---------------- 提醒调度 ----------------
def reminder_loop():
    """每 30 秒查一次到期提醒，弹 Windows 原生通知（点开直达那条笔记）。
    带 repeat=daily 的笔记（「每天HH:MM」语法糖）触发后自动排到明天同一时刻。"""
    while True:
        try:
            for n in store.due_reminders():
                store.mark_reminder_fired(n["id"])
                msg = (n.get("text") or "")[:200]
                url = panel_url(n["id"])
                daily = n.get("repeat") == "daily"
                native_toast("⏰ 每天" if daily else "⏰ 提醒", msg, launch=url,
                             actions=[("📋 打开面板", url)])
                if daily:
                    import datetime as _dt
                    ra = n.get("remind_at", "")
                    try:
                        t = _dt.datetime.fromisoformat(ra)
                        step = 7 if n.get("repeat") == "weekly" else 1
                        nxt = (t + _dt.timedelta(days=step)).isoformat(timespec="seconds")
                        store.set_reminder(n["id"], nxt)   # set_reminder 会复位 remind_fired
                        log.info("recurring reminder rescheduled -> %s", nxt)
                        continue
                    except (ValueError, TypeError):
                        pass
                log.info("reminder fired: %s", n.get("id"))
        except Exception as e:
            log.warning("reminder loop error: %s", e)
        time.sleep(30)


# ---------------- 联系人待办到期提醒 ----------------
def contact_todo_reminder_loop():
    """每 20 秒扫联系人待办：到 remind_at 且未提醒未完成 → 弹原生通知。"""
    import contacts as _ct
    while True:
        try:
            for item in _ct.due_contact_todos():
                c, t = item["contact"], item["todo"]
                _ct.mark_contact_todo_reminded(c["id"], t["id"])
                base = panel_url()
                cid, tid = c["id"], t["id"]
                native_toast("⏰ " + (t.get("text") or "待办")[:40],
                             "联系人：" + c.get("name", ""),
                             launch=base + "#page=contacts",
                             actions=[
                                 ("✅ 完成", base + "#ctdone=%s/%s" % (cid, tid)),
                                 ("+1小时", base + "#ctsnooze=%s/%s/1" % (cid, tid)),
                                 ("+2小时", base + "#ctsnooze=%s/%s/2" % (cid, tid)),
                                 ("+3小时", base + "#ctsnooze=%s/%s/3" % (cid, tid)),
                             ])
                log.info("contact todo reminder fired: %s / %s",
                         c.get("name"), t.get("id"))
        except Exception as e:
            log.warning("contact todo reminder error: %s", e)
        time.sleep(20)


# ---------------- 断网出门感应（宿舍网在线记的待办，出门自动提醒） ----------------
_net_session = {"key": None, "since": 0.0, "learned": False}


def _maybe_learn_home(st):
    """自动认识常驻网络：同一个网连续待满 learn_hours 小时 → 记为「家」之一。
    开学回宿舍连上网挂一夜就自动注册，无需手动配置；换城市长住同理。"""
    key = st.get("gw_mac") or st.get("ssid") or ""
    now_ts = time.time()
    if key != _net_session["key"]:
        _net_session.update(key=key, since=now_ts, learned=False)
        return
    if not key or _net_session["learned"]:
        return
    try:
        learn_hours = float(config.load().get("away_sense", {}).get("learn_hours", 6) or 6)
    except Exception:
        learn_hours = 6.0
    if now_ts - _net_session["since"] < learn_hours * 3600:
        return
    _net_session["learned"] = True
    cfgc = config.load()
    a = cfgc.setdefault("away_sense", {})
    changed = False
    macs = [str(m).lower() for m in a.get("home_gateway_macs", [])]
    if st.get("gw_mac") and st["gw_mac"].lower() not in macs:
        a.setdefault("home_gateway_macs", []).append(st["gw_mac"].lower())
        changed = True
    if st.get("ssid") and st.get("ssid") not in a.get("home_ssids", []):
        a.setdefault("home_ssids", []).append(st["ssid"])
        changed = True
    if changed:
        config.save(cfgc)
        native_toast("🏠 已认识新常驻地",
                     "出门感应在这个网也会生效：" + (st.get("ssid") or st.get("gw_mac") or "")[:40])
        log.info("away-sense learned home network: ssid=%s gw=%s",
                 st.get("ssid"), st.get("gw_mac"))


def away_watch_loop():
    """每 ~20 秒读一次网络状态（netwatch 双指纹：SSID+网关MAC），
    确认「在家→离家」沿后弹一次未完成待办汇总；没待办就静默。"""
    import netwatch
    import contacts as _ct
    mon = None
    interval = 20
    while True:
        try:
            cfg = config.load().get("away_sense", {})
            interval = int(cfg.get("check_interval", 20) or 20)
            if cfg.get("enabled", True):
                want = max(1, int(cfg.get("confirm_checks", 4) or 4))
                if mon is None or mon.confirm != want:
                    mon = netwatch.AwayMonitor(confirm=want)
                st = netwatch.get_network_state()
                raw = netwatch.classify_state(st, cfg)
                _maybe_learn_home(st)
                edge = mon.update(raw)
                if edge == "depart":
                    todos = _ct.pending_contact_todos()
                    if todos:
                        lines = "；".join("· " + (t["todo"].get("text") or "")[:24]
                                          for t in todos[:3])
                        extra = "" if len(todos) <= 3 else " 等%d件" % len(todos)
                        url = panel_url() + "#page=contacts"
                        native_toast("🚪 出门了，有 %d 件待办没办" % len(todos),
                                     lines + extra,
                                     launch=url,
                                     actions=[("📋 打开面板", url)])
                        log.info("away depart fired: %d pending todos", len(todos))
                    else:
                        log.info("away depart: no pending todos, silent")
                elif edge == "arrive":
                    log.info("away arrive: back on home network")
                else:
                    log.debug("net state raw=%s ssid=%s gw=%s",
                              raw, st.get("ssid"), st.get("gw_mac"))
        except Exception as e:
            log.warning("away watch error: %s", e)
            mon = None
        time.sleep(interval)


# ---------------- 录音待转写监视（手机录音 → 电脑转写 → 同步回手机） ----------------
def transcribe_watch_loop():
    import transwatch

    def _notify(text, nid):
        url = panel_url(nid)
        native_toast("📱 手机录音已转成文字", (text or "")[:80],
                     launch=url, actions=[("📋 打开面板", url)])

    transwatch.watch_loop(interval=10, notify=_notify)


# ---------------- 稍后读（剪贴板网址自动收 + 热键手动 + 抓标题正文） ----------------
def readlater_loop():
    import readlater

    def _notify(text, nid):
        url = panel_url(nid) if nid else None
        native_toast("📖 稍后读", (text or "")[:80], launch=url)

    readlater.watch_loop(notify=_notify)


# ---------------- 生日提醒（每天到点：当天祝贺 + 3 天预告） ----------------
def birthday_reminder_loop():
    import datetime as _dt
    import contacts as _ct
    notified_date = None
    while True:
        try:
            cfg = config.load().get("birthday", {})
            if cfg.get("enabled", True):
                hhmm = cfg.get("remind_time", "08:00")
                now = _dt.datetime.now()
                today = now.strftime("%Y-%m-%d")
                if notified_date != today and now.strftime("%H:%M") >= hhmm:
                    notified_date = today   # 无论结果如何，今天不再查
                    url = panel_url() + "#page=contacts"
                    hits = _ct.today_birthdays(now)
                    if hits:
                        names = "、".join(c.get("name", "") for c in hits)
                        title = ("🎂 今天是 %s 的生日" % names if len(hits) == 1
                                 else "🎂 今天有 %d 位寿星：%s" % (len(hits), names))
                        native_toast(title, "别忘了送上祝福～", launch=url,
                                     actions=[("👥 打开人脉", url)])
                        log.info("birthday reminder fired: %s", names)
                    ups14 = [x for x in _ct.upcoming_birthdays(days=14, now=now)
                             if x[2] == 14]
                    if ups14:
                        lines = "；".join("%s 的生日（%d月%d日）"
                                          % (c.get("name", ""), md[0], md[1])
                                          for c, md, d in ups14[:3])
                        native_toast("🎁 两周后有生日，该准备礼物了", lines,
                                     launch=url, actions=[("👥 打开人脉", url)])
                        log.info("birthday 2-week notice: %d", len(ups14))
                    ups3 = [x for x in _ct.upcoming_birthdays(days=3, now=now)
                            if x[2] == 3]
                    if ups3:
                        lines = "；".join("%s 的生日（%d月%d日）还有 3 天"
                                          % (c.get("name", ""), md[0], md[1])
                                          for c, md, d in ups3[:3])
                        native_toast("🎁 生日快到了", lines,
                                     launch=url, actions=[("👥 打开人脉", url)])
                        log.info("birthday 3-day notice: %d", len(ups3))
        except Exception as e:
            log.warning("birthday reminder error: %s", e)
        time.sleep(60)


# ---------------- 数据自动备份（每天一个 zip，滚动保留 14 份）+ 回收站月度清理 ----------------
def backup_loop():
    import backups
    cfg = config.load().get("backup", {})
    if not cfg.get("enabled", True):
        return
    bdir = os.path.join(BASE, "data", "backups")
    last_purge = None
    while True:
        try:
            backups.make_backup(store.notes_dir(), bdir,
                                keep=int(cfg.get("keep", 14) or 14))
            pcfg = config.load().get("trash_autopurge", {})
            today = time.strftime("%Y-%m-%d")
            if pcfg.get("enabled", True) and last_purge != today:
                last_purge = today
                n = store.purge_old_trash(days=int(pcfg.get("days", 30) or 30))
                if n:
                    log.info("trash autopurged: %d notes (>%sd)",
                             n, pcfg.get("days", 30))
        except Exception as e:
            log.warning("backup loop error: %s", e)
        time.sleep(1800)


# ---------------- 收件夹视觉入库（P1：截图 → 本地视觉模型 → 待确认） ----------------
def inbox_watch_loop():
    import vision
    vision.watch_loop(interval=60)


# ---------------- 上课提醒（P3：课前 15 分钟，按周次过滤） ----------------
def course_reminder_loop():
    import datetime as _dt
    import courses as _co
    fired = {}          # course_id+日期+开始时间 → 已提醒
    while True:
        try:
            cfg = config.load().get("course", {})
            if cfg.get("remind_enabled", True):
                window = int(cfg.get("remind_minutes", 15) or 15)
                today = _dt.datetime.now().strftime("%Y-%m-%d")
                for item in _co.due_soon(window_minutes=window):
                    c = item["course"]
                    key = "%s|%s|%s" % (c.get("id"), today, c.get("start"))
                    if fired.get(key):
                        continue
                    fired[key] = True
                    native_toast(
                        "📚 %s %s 有《%s》" % (c.get("start"), c.get("place") or "待定教室",
                                              c.get("name", "课程")),
                        "还有约 %d 分钟上课（课前 %d 分钟提醒）" % (item["minutes_away"], window),
                        launch=panel_url())
                    log.info("course reminder: %s %s", c.get("name"), c.get("start"))
        except Exception as e:
            log.warning("course reminder error: %s", e)
        time.sleep(60)


# ---------------- 出门提醒（托盘可手动测试，与真实出门同路径） ----------------
def fire_departure_notice_test():
    try:
        import contacts as _ct
        todos = _ct.pending_contact_todos()
        if todos:
            lines = "；".join("· " + (t["todo"].get("text") or "")[:24]
                              for t in todos[:3])
            extra = "" if len(todos) <= 3 else " 等%d件" % len(todos)
            url = panel_url() + "#page=contacts"
            native_toast("🚪 [测试] 出门了，有 %d 件待办没办" % len(todos),
                         lines + extra, launch=url,
                         actions=[("📋 打开面板", url)])
        else:
            native_toast("🚪 [测试] 出门提醒就绪",
                         "现在没有未完成的待办，真出门时不会打扰你。")
        log.info("away depart TEST fired: %d pending todos", len(todos))
    except Exception as e:
        log.warning("away test error: %s", e)


# ---------------- 速记悬浮窗（联想键/托盘唤出） ----------------
QUICKNOTE_PORT = 8780
_qn_proc = None


def _qn_send(msg):
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.sendto(json.dumps(msg).encode("utf-8"), ("127.0.0.1", QUICKNOTE_PORT))
        sk.close()
    except Exception:
        pass


_overlay_alive = False


def _overlay_ok():
    """悬浮层进程真活着才算活着。收编时代进程在、窗口死的僵尸会把所有弹窗吞进虚空
    （2026-09-07 天禧键/F10「失灵」真凶），所以每次用前都验一遍，死了自动走兜底。"""
    global _overlay_alive
    _overlay_alive = bool(_qn_proc is not None and _qn_proc.poll() is None)
    return _overlay_alive


def ensure_overlay():
    """拉起悬浮层 v2（tkinter 引擎）：系统 Python 3.14 运行 overlay.py。
    pywebview 版（存档 .zcode_backup/overlay_pywebview_last.py）因 WebView2
    运行时自动更新导致渲染全灭，已按用户拍板换回 tkinter 方案二。"""
    global _overlay_alive, _qn_proc
    _kill_luyuan_py("overlay.py")    # 清掉任何旧悬浮层（含 pywebview 版）
    _kill_luyuan_py("quicknote.py")  # 旧 tkinter 速记窗也占 8780（僵尸教训）
    pre = find_gui_python()          # 需要 tkinter：系统 Python 3.14
    if not pre:
        log.warning("悬浮层不可用：未找到带 tkinter 的 Python")
        _overlay_alive = False
        _qn_proc = None
        return
    try:
        _qn_proc = subprocess.Popen(
            pre + [os.path.join(BASE, "overlay.py")],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.warning("悬浮层启动失败：%s", e)
        _qn_proc = None
        _overlay_alive = False
        return
    time.sleep(2.0)
    _overlay_alive = _qn_proc.poll() is None
    log.info("overlay fresh process started (tkinter), alive=%s", _overlay_alive)


def open_quicknote():
    """唤出速记卡片：悬浮层优先，tkinter 速记窗兜底。"""
    if _overlay_ok():
        _qn_send({"kind": "quicknote"})
        return
    # 兜底：旧 tkinter 速记窗
    global _qn_proc
    pre = find_gui_python()
    if not pre:
        native_toast("⚠️ 速记窗不可用", "未找到系统 Python 3.14")
        return
    if _qn_proc is None or _qn_proc.poll() is not None:
        try:
            _qn_proc = subprocess.Popen(
                pre + [os.path.join(BASE, "quicknote.py")],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.2)
        except Exception as e:
            log.warning("速记窗启动失败：%s", e)
            return
    _qn_send({"kind": "show"})


def stop_overlay():
    """退出时收掉悬浮层浮窗进程，杜绝「主程序关了浮窗还在」的孤儿（2026-09-13）。
    先发 quit 让浮层自己销毁，再 terminate 兜底（浮层内另有父进程看门狗双保险）。
    ⚠️ 只在「本进程确实拉起过浮层」时才动手：否则第二个实例（互斥锁早退）
    的 atexit 会发 quit 误杀正在运行实例的浮窗。"""
    global _qn_proc
    if _qn_proc is None:
        return
    try:
        _qn_send({"kind": "quit"})
    except Exception:
        pass
    time.sleep(0.4)
    try:
        if _qn_proc.poll() is None:
            _qn_proc.terminate()
    except Exception:
        pass
    try:
        _qn_proc.wait(timeout=3)
    except Exception:
        try:
            _qn_proc.kill()
        except Exception:
            pass
    _qn_proc = None
    log.info("overlay stopped")


# ---------------- 日记提醒（负一屏） ----------------
def diary_reminder_loop():
    """每天到点检查：今天还没写日记就弹一条原生通知（一天最多提醒一次）。"""
    import datetime as _dt
    notified = None
    while True:
        try:
            cfg = config.load().get("diary", {})
            if cfg.get("enabled", True):
                hhmm = cfg.get("remind_time", "21:30")
                now = _dt.datetime.now()
                today = now.strftime("%Y-%m-%d")
                if notified != today and now.strftime("%H:%M") >= hhmm:
                    has = any(str(n.get("created_at", "")).startswith(today)
                              for n in store.list_notes(tag="日记", limit=50))
                    notified = today   # 无论有没有写，今天不再提醒
                    if not has:
                        url = panel_url() + "#page=diary"
                        native_toast("📝 今天还没写日记",
                                     "去「日记」页记两笔，别断了连击",
                                     launch=url,
                                     actions=[("📝 去写日记", url)])
                        log.info("diary reminder fired")
        except Exception as e:
            log.warning("diary reminder error: %s", e)
        time.sleep(60)


# ---------------- 手机新笔记监视 ----------------
def phone_watch_loop():
    """监视 notes 目录：手机(device=phone)经 Syncthing 同步来新笔记 → 弹通知。"""
    import transwatch
    seen = {n["id"] for n in store.list_notes(limit=500)}
    while True:
        try:
            for n in store.list_notes(limit=50):
                if n["id"] in seen:
                    continue
                seen.add(n["id"])
                if n.get("device") == "phone":
                    native_toast("📱 你在外面记了一条",
                                 (n.get("text") or "")[:40],
                                 actions=[("📋 打开面板",
                                           "http://127.0.0.1:{port}/#n={nid}".format(
                                               port=config.load()["server"].get("port", 8777),
                                               nid=n["id"]))])
                    log.info("phone note toast: %s", n["id"][:8])
                    # 手机分享来的纯网址 → 交给稍后读管线抓标题正文（2026-09-09）
                    try:
                        import readlater as _rlm
                        _url = _rlm.normalize_url(n.get("text", ""))
                        if _url:
                            store.add_tag(n["id"], "稍后读")
                            store.set_field(n["id"], "rl_state", "pending")
                            store.set_field(n["id"], "link", _url)
                            log.info("phone URL -> read later: %s", n["id"][:8])
                            continue
                    except Exception as e:
                        log.info("phone url check error: %s", e)
                    # 手机笔记同样走智能捕获（归类/联系人待办/提醒）；
                    # 但「语音待转写」占位笔记跳过——等 transwatch 转出真文本再归类，
                    # 否则占位符先被打上错标签、转写后旧标签还挂着（标签污染）
                    if transwatch.PLACEHOLDER_MARK in (n.get("text") or ""):
                        log.info("phone note %s is placeholder, classify deferred to transwatch",
                                 n["id"][:8])
                    else:
                        try:
                            import classify
                            classify.classify_async(n["id"], n.get("text", ""))
                        except Exception:
                            pass
        except Exception as e:
            log.warning("phone watch error: %s", e)
        time.sleep(10)


# ---------------- 热键 ----------------
_HOTKEY_STATE = {"rl_last": 0.0, "started": False}


def start_hotkey():
    if _HOTKEY_STATE["started"]:
        log.warning("start_hotkey 已注册过，跳过重复注册（防止 F7 双触发）")
        return
    _HOTKEY_STATE["started"] = True
    try:
        from pynput.keyboard import GlobalHotKeys
        cfg = config.load().get("hotkey", {})
        combo = cfg.get("combo", "<f10>")
        if not cfg.get("enabled", True):
            return

        def _cb():
            try:
                log.info("hotkey %s pressed (state=%s)", combo,
                         bridge.get_status().get("state"))
                toggle_capture()
            except Exception as e:
                log.warning("hotkey callback error: %s", e)

        def _open_ui():
            try:
                log.info("hotkey <f9> pressed (open panel)")
                open_browser()
            except Exception as e:
                log.warning("open ui hotkey error: %s", e)

        # F9：一键打开主界面（极简便捷原则，固定绑定，不进 config）
        binds = {combo: _cb, "<f9>": _open_ui}
        # 速记悬浮窗热键（探测联想键后写入 config.quicknote.hotkey）
        # 天禧键专占（2026-09-07）：速记热键绑在 F23 上时，用 win32_event_filter
        # 在钩子层吞掉 F23——pynput 钩子比联想后装、优先级更高，suppress 后
        # 联想/系统都收不到这颗键，Windows 搜索兜底弹窗从此绝迹。
        qn_combo = config.load().get("quicknote", {}).get("hotkey", "")
        f23_owned = "f23" in qn_combo.lower()
        _hk_holder = {}

        def _tianxi_filter(msg, data):
            if not f23_owned:
                return True
            _swallow = False
            try:
                if getattr(data, "vkCode", 0) == 0x86:      # VK_F23 = 134（0x76 是 F7！）
                    if msg in (0x0100, 0x0104):              # KEYDOWN
                        log.info("F23 swallowed (quicknote exclusive)")
                        threading.Thread(target=open_quicknote,
                                         daemon=True).start()
                    _swallow = True
            except Exception as e:
                log.warning("tianxi filter error: %s", e)
            if _swallow:
                # 吞键必须在 try 之外执行：suppress_event() 抛
                # SystemHook.SuppressException，被 try 截住就吞键失效，
                # 必须让它穿透本函数上抛给 pynput（2026-09-09 教训）。
                # 2026-09-11 修：旧代码 except 引用了从未定义的
                # _PynputSuppressException → 每按一次天禧键 NameError，
                # 热键监听器崩溃重启、F10/F9 闪断。挪出 try 后异常自然穿透。
                _l = _hk_holder.get("listener")
                if _l:
                    _l.suppress_event()   # 异常穿透 → 真正吞键
            return True

        if qn_combo and not f23_owned:
            def _qn():
                try:
                    log.info("hotkey %s pressed (quicknote)", qn_combo)
                    open_quicknote()
                except Exception as e:
                    log.warning("quicknote hotkey error: %s", e)
            binds[qn_combo] = _qn
            log.info("quicknote hotkey %s registered", qn_combo)

        # 📖 稍后读热键（v1.38，默认 F7，config.readlater.hotkey 可改）：
        # 剪贴板里是纯网址就立刻收进稍后读并抓正文
        rl_combo = config.load().get("readlater", {}).get("hotkey", "<f7>")
        if rl_combo and rl_combo not in binds:
            def _rl():
                try:
                    # 防抖：1.5s 内重复触发（按键连发 / 多实例残留监听）只认一次，
                    # 避免一次 F7 收两条稍后读或弹两次提示。
                    _now = time.time()
                    if _now - _HOTKEY_STATE["rl_last"] < 1.5:
                        log.info("readlater 防抖：忽略 1.5s 内重复触发")
                        return
                    _HOTKEY_STATE["rl_last"] = _now
                    log.info("hotkey %s pressed (read later)", rl_combo)
                    import readlater
                    readlater.save_from_clipboard(
                        manual=True,
                        notify=lambda text, nid: native_toast("📖 稍后读",
                                                              (text or "")[:80],
                                                              launch=panel_url(nid) if nid else None))
                except Exception as e:
                    log.warning("readlater hotkey error: %s", e)
            binds[rl_combo] = _rl
            log.info("readlater hotkey %s registered", rl_combo)

        # 📋 选中即存热键（用户指定 <ctrl>+<alt>+c，config.readlater.select_hotkey 可改）：
        # 选中文字按组合键 → 自动 Ctrl+C 把选中内容拷进剪贴板 → 存进路远
        # （纯网址进「稍后读」抓正文，其它文字进「收藏」笔记）。需先有选中内容。
        sel_combo = config.load().get("readlater", {}).get(
            "select_hotkey", "<ctrl>+<alt>+c")
        if sel_combo and sel_combo not in binds:
            def _sel():
                try:
                    _now = time.time()
                    if _now - _HOTKEY_STATE.get("sel_last", 0) < 1.5:
                        log.info("select hotkey 防抖：忽略 1.5s 内重复触发")
                        return
                    _HOTKEY_STATE["sel_last"] = _now
                    log.info("hotkey %s pressed (save selection)", sel_combo)
                    import readlater
                    threading.Thread(
                        target=readlater.save_selection_to_luyuan,
                        kwargs={"notify": lambda t, nid: native_toast(
                            "📋 存进路远", (t or "")[:80],
                            launch=panel_url(nid) if nid else None)},
                        daemon=True).start()
                except Exception as e:
                    log.warning("save selection hotkey error: %s", e)
            binds[sel_combo] = _sel
            log.info("save-selection hotkey %s registered", sel_combo)

        def _spawn():
            hot = GlobalHotKeys(binds, win32_event_filter=_tianxi_filter)
            _hk_holder["listener"] = hot
            threading.Thread(target=hot.start, daemon=True).start()
            return hot

        hot = _spawn()
        log.info("hotkey %s / <f9>(open ui) registered", combo)

        # 看门狗：监听线程意外死亡时自动重建（F10 失灵自愈）
        def _watchdog():
            nonlocal hot
            while True:
                time.sleep(5)
                try:
                    if not hot.is_alive():
                        log.warning("hotkey listener died, restarting")
                        hot = _spawn()
                except Exception as e:
                    log.warning("hotkey watchdog error: %s", e)

        threading.Thread(target=_watchdog, daemon=True).start()
    except Exception as e:
        log.warning("hotkey unavailable: %s", e)


# ---------------- 唤醒词 ----------------
def start_wakeword():
    try:
        import wakeword
        def _on_ww():
            # 唤醒后压一段较长静默，双保险防连环触发；
            # 用 safe 版，流水线正忙则跳过（不会堆叠）
            bridge.set_ww_cooldown(8.0)
            bridge.request_capture_safe()
        ww = wakeword.WakeWordDetector(on_detect=_on_ww)
        ww.stop_event = ww_stop
        threading.Thread(target=ww.run, daemon=True).start()
        log.info("wakeword listener started")
    except Exception as e:
        log.info("wakeword disabled: %s", e)


def restart_wakeword():
    global ww_stop
    ww_stop.set()
    time.sleep(0.6)
    ww_stop.clear()
    start_wakeword()


def _wakeword_enabled():
    try:
        return bool(config.load().get("wakeword", {}).get("enabled", False))
    except Exception:
        return False


def set_wakeword(on):
    """运行时开关唤醒词，并持久化到 config（托盘一键切换，2026-09-13）。
    用户嫌它乱触发时，不必改文件，托盘点一下即可关。"""
    on = bool(on)
    try:
        cfg = config.load()
        cfg.setdefault("wakeword", {})["enabled"] = on
        config.save(cfg)
    except Exception as e:
        log.warning("set_wakeword save failed: %s", e)
    if on:
        restart_wakeword()
    else:
        ww_stop.set()
    log.info("wakeword %s (tray toggle)", "enabled" if on else "disabled")


def toggle_wakeword(i=None, item=None):
    set_wakeword(not _wakeword_enabled())


# ---------------- 托盘 ----------------
def make_icon():
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (16, 20, 28, 255))
        d = ImageDraw.Draw(img)
        d.ellipse((12, 12, 52, 52), fill=(90, 150, 255, 255))
        d.text((25, 22), "路", fill=(255, 255, 255, 255))
        return img
    except Exception:
        return None


def build_menu():
    from pystray import Menu, MenuItem

    def open_panel(i, item):
        open_browser()

    def capture_menu(i, item):
        bridge.request_capture()

    def stop_menu(i, item):
        bridge.request_stop()

    def reload_ww(i, item):
        restart_wakeword()

    def quit_app(i, item):
        ww_stop.set()
        stop_overlay()      # 先收浮层，杜绝「主程序关了浮窗还在」
        stop_server()
        icon.stop()

    def _ww_label(item):
        return ("🔊 唤醒词：开（点击关）" if _wakeword_enabled()
                else "🔇 唤醒词：关（点击开）")

    return Menu(
        MenuItem("打开面板", open_panel, default=True),
    MenuItem("⚡ 速记窗", lambda i, item: open_quicknote()),
        MenuItem("开始记录", capture_menu),
        MenuItem("停止记录", stop_menu),
        MenuItem(_ww_label, toggle_wakeword),
        MenuItem("🧪 出门提醒测试", lambda i, item: fire_departure_notice_test()),
        MenuItem("重载唤醒词", reload_ww),
        Menu.SEPARATOR,
        MenuItem("退出", quit_app),
    )


def start_server():
    """把 Web 服务作为独立进程拉起（而非主进程内的线程）。

    解耦原因：主进程还跑托盘 / 浮层 / 剪贴板 / 全局热键等 GUI 原生组件，
    在异常会话（无交互桌面）里这些组件可能段错误，会把整个进程（含服务）
    一起带走。拆成独立进程后，GUI 进程即使崩了，8777 上的服务依然存活。
    """
    global _server_proc
    try:
        # 幂等保护改为「端口探测」（2026-09-11 优化）：8777 已有人监听就不重复拉起。
        # 原先这里无条件跑 PowerShell 杀 server_runner + sleep 1s，每次启动白耗 ~1.5s，
        # 且与 launcher / main() 的清场重复——server_runner 自身还有端口单实例保护
        # （绑不上会自己退出），双保险已足够，不需要第三层互相清场。
        cfg = config.load()["server"]
        import socket as _sock
        _probe_host = "127.0.0.1" if cfg["host"] in ("0.0.0.0", "::") else cfg["host"]
        _s = _sock.socket()
        _s.settimeout(0.5)
        try:
            _s.connect((_probe_host, cfg["port"]))
            log.info("start_server: 端口 %s 已有服务监听，跳过重复拉起", cfg["port"])
            return
        except OSError:
            pass
        finally:
            try:
                _s.close()
            except Exception:
                pass
        py = sys.executable
        script = os.path.join(BASE, "server_runner.py")
        _server_proc = subprocess.Popen(
            [py, script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log.info("start_server: 已作为独立进程拉起 uvicorn (pid=%s) %s:%s",
                 _server_proc.pid, cfg["host"], cfg["port"])
    except Exception:
        log.exception("start_server 独立进程拉起失败（served 端口未绑定）")


def stop_server():
    """退出时杀掉 Web 服务子进程**及其整个进程树**，避免孤儿占用 8777。

    ⚠️ 2026-09-13 根因修复：原先只 terminate 直接子进程，但 uvicorn 还会再
    spawn 一个 worker（实测 8777 上 LISTENING 的正是那个 worker）→ worker 成
    孤儿继续占端口 → 下次启动一看 8777 被占，就误判「已有实例在跑」而拒绝
    启动（表现为双击后没托盘、热键/唤醒词全不出来）。
    现在：taskkill /T 连树一起杀 + 兜底扫描清掉任何残留 server_runner。"""
    global _server_proc
    owned = _server_proc is not None   # 只有「本进程确实拉起过服务」才做清理：
                                       # 否则第二实例早退时的 atexit 会误杀健康实例的服务
    if owned:
        try:
            subprocess.run(["taskkill", "/PID", str(_server_proc.pid), "/T", "/F"],
                           stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
        try:
            _server_proc.wait(timeout=3)
        except Exception:
            try:
                _server_proc.kill()
            except Exception:
                pass
        _server_proc = None
    if owned:
        # 兜底：扫掉任何仍赖着的 server_runner.py（含 uvicorn 自己 spawn 的 worker）
        try:
            _free_orphan_server()
        except Exception:
            pass


atexit.register(stop_server)   # 兜底：主进程退出时清理 Web 服务子进程
atexit.register(stop_overlay)  # 兜底：退出时收掉悬浮层浮窗，杜绝孤儿窗口


def preload_stt():
    """后台预载语音模型：避免第一次 F10 转写等 30 秒冷启动。"""
    try:
        stt.get_model()
        log.info("stt model preloaded (first transcribe will be fast)")
    except Exception as e:
        log.warning("stt preload failed: %s", e)


def _safe_ensure_overlay():
    """后台线程安全地拉起悬浮层：异常不影响主程序（托盘/热键照常）。"""
    try:
        log.info("[诊断] ensure_overlay 开始（后台线程）")
        ensure_overlay()
        log.info("[诊断] ensure_overlay 结束")
    except Exception as e:
        log.exception("悬浮层启动异常（后台线程，不影响主程序）: %s", e)


def _safe_ensure_notifier():
    """后台线程安全地拉起指示窗：异常不影响主程序。"""
    try:
        ensure_notifier()
    except Exception as e:
        log.exception("指示窗启动异常（后台线程，不影响主程序）: %s", e)


def _scan_main_pids(me):
    """扫出其它 main.py 进程的 PID 列表（排除自己 + 直接父进程）。异常返回 []。

    ⚠️ 2026-09-13：必须排除父进程——venv 的 .venv\\Scripts\\python.exe 是**启动器**，
    它会派生一个**命令行完全相同**的子进程来真正跑 main()；子进程扫描时会把
    父进程误认成「另一个实例」（用户 09-13「双击后没托盘」真凶之一）。"""
    try:
        ppid = os.getppid()
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*<project-root>\\main.py*' -and "
             "$_.ProcessId -ne %d -and $_.ProcessId -ne %d } | "
             "Select-Object -ExpandProperty ProcessId" % (me, ppid)],
            stderr=subprocess.DEVNULL, encoding="gbk", errors="ignore", timeout=10)
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def _other_main_running():
    """是否有别的「健康」路远 main.py 进程在跑（排除自己），用于单实例自检。

    ⚠️ 二次确认（2026-09-13 根因修复）：老实例退出时会经历一段「锁已释放、
    进程尚未死、服务尚未清」的尾巴（几百毫秒~数秒）。此时首次扫描会扫到它，
    若直接判定「已在运行」→ 新启动的实例会**直接放弃启动**，表现为
    「双击路远后没有托盘、热键/唤醒词全不出来」（用户 09-13 实测）。
    所以首次命中后等 1.5s 复查：仍在 → 真·健康实例；已消失 → 退出的尾巴，
    视为没有实例，继续正常启动。"""
    me = os.getpid()
    if not _scan_main_pids(me):
        return False
    time.sleep(1.5)
    return bool(_scan_main_pids(me))


def _free_orphan_server():
    """清掉孤儿 server_runner.py（主进程已死但仍占 8777 的情况）。"""
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*<project-root>\\server_runner.py*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        pass


def _acquire_main_mutex():
    """主进程互斥锁（2026-09-08 深夜硬ening）：健康 main 活着时，新实例
    安详退出（只开面板），**绝不互杀**。旧版按 cmdline 扫描互杀——清场
    PowerShell 有启动延迟，孤儿清场窗口会把健康实例带走（当晚实测两次）。
    互斥锁由内核管理：进程死锁自动释放，无残留问题。
    ⚠️ 必须 use_lasterror=True：windll 默认不捕获，GetLastError 返回垃圾值，
    「已存在」判定会失效（当晚第一版就栽在这，双实例复现）。"""
    import ctypes
    k32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, 0, _MAIN_MUTEX_NAME)
    if not h:
        return "ok"   # 创建失败不拦：宁可极端情况多开，不可误杀正常启动
    global _MAIN_MUTEX
    _MAIN_MUTEX = h   # 进程存活期间持有引用，防止被回收
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        # ⚠️ 2026-09-13：撞锁时必须**立刻关掉自己这个句柄**。
        # 句柄开着本身就是"替对方的锁对象续命"——对方进程死后，只要还有任意
        # 句柄存在，锁对象就不会销毁，CreateMutexW 永远报「已存在」→
        # 「等旧实例退出后接管」的重试逻辑会被自己卡死。
        k32.CloseHandle(h)
        _MAIN_MUTEX = None
        return "taken"
    return "ok"


def _server_alive(timeout=0.6):
    """8777 上是否有服务在监听（用于区分「真实例」和「正在收尾的旧实例」）。"""
    import socket as _s
    try:
        port = config.load()["server"]["port"]
        sk = _s.socket()
        sk.settimeout(timeout)
        sk.connect(("127.0.0.1", port))
        sk.close()
        return True
    except Exception:
        return False


def _try_take_over_mutex(max_wait=10.0, poll=1.0):
    """拿主进程锁；锁在位时判断持有者是否真的还活着。

    ⚠️ 2026-09-13 用户实测根因（症状：「我重启之后热键无法使用」）：
    旧实例退出是**延迟释放**的——主进程先关浮层/托盘、服务已停，但内核要等
    进程真正结束才释放锁（今天实测尾巴有 ~9s：15:07:59 停、15:08:11 才收干净）。
    这个窗口里双击启动的新实例会撞上锁 → 只弹一个面板就 return →
    **托盘没起、热键一条没注册**，用户体感「重启了但热键全死」。

    判据：
      锁在位 **且** 8777 有服务 → 确实是健康实例在跑 → 安详退出（只开面板）
      锁在位 **但** 8777 没服务 → 视为「收尾中的旧实例」→ 等锁释放后接管启动
    最多等 max_wait 秒；等到了就正常启动，等不到仍按原样安详退出（绝不互杀）。
    """
    waited = 0.0
    while True:
        if _acquire_main_mutex() == "ok":
            if waited:
                log.info("旧实例已退净（等锁 %.1fs），本次接管启动", waited)
            return "ok"
        if _server_alive():
            return "taken"          # 真实例在服务 → 立刻让位
        if waited >= max_wait:
            return "taken"          # 等够了还不放锁 → 保守让位
        time.sleep(poll)            # 句柄已被 _acquire_main_mutex 关掉，能等到释放
        waited += poll


def _install_crash_hooks():
    """任何线程的未捕获异常都追加落盘 data/startup_error.log（消灭静默死）。"""
    import sys
    import threading
    import traceback as _tb

    def _write(tag, exc):
        try:
            import datetime
            with open(os.path.join(BASE, "data", "startup_error.log"),
                      "a", encoding="utf-8") as f:
                f.write("\n[%s] %s\n" % (
                    datetime.datetime.now().isoformat(timespec="seconds"), tag))
                _tb.print_exception(type(exc), exc, exc.__traceback__, file=f)
        except Exception:
            pass

    def _sys_hook(t, v, tb):
        _write("sys.excepthook", v)
        sys.__excepthook__(t, v, tb)

    def _thr_hook(a):
        _write("thread=%s" % getattr(a.thread, "name", "?"), a.exc_value)

    sys.excepthook = _sys_hook
    threading.excepthook = _thr_hook


_MAIN_MUTEX = None
# 内核命名互斥锁名（单实例唯一权威判据）。提成模块常量便于测试替换。
_MAIN_MUTEX_NAME = "Local\\LuyuanMainKernel"


def main():
    global icon
    log.info("路远 main.py 启动 (pid=%d)", os.getpid())
    _install_crash_hooks()
    # 单实例互斥锁：已有健康主进程 → 只开面板，安详退出（不杀任何人）
    if _try_take_over_mutex() == "taken":
        log.info("已有路远主进程在跑（互斥锁在位 + 8777 有服务），只开面板不重复启动")
        try:
            native_toast("路远已在运行", "面板已为你打开，不用重复启动")
        except Exception:
            pass
        try:
            open_browser()
        except Exception:
            pass
        return
    # 端口自检先行（socket 探测，快）：端口空着就完全跳过 PowerShell 清场。
    # 优化（2026-09-11）：原先无条件跑 PowerShell 杀 server_runner + sleep 1s，
    # 冷启动端口明明是空的也白跑白等 ~2s。孤儿场景（8777 被占）才走清理。
    import socket as _sock
    _cfg = config.load()["server"]
    _occupied = False
    _s = _sock.socket()
    _s.settimeout(1)
    try:
        _s.connect(("127.0.0.1", _cfg["port"]))
        _occupied = True
    except Exception:
        pass
    finally:
        _s.close()
    if _occupied:
        # 单实例已由上面的内核互斥锁把关（真有健康实例，锁分支早已 return），
        # 所以走到这里必然是「孤儿 server_runner / 旧实例残留占着 8777」→ 清掉接管。
        #
        # ⚠️ 2026-09-13 根因修复（用户实测：双击后无托盘、热键全死）：
        # 原先这里再调 _other_main_running()（按 cmdline 扫 '*D:\Luyuan\main.py*'），
        # 但 venv 的 .venv\Scripts\python.exe 是**启动器**，它会派生一个**命令行
        # 完全相同**的子进程来真正跑 main()——子进程扫描时扫到自己的父进程，
        # 误判「另一个实例在跑」→ 直接放弃启动。互斥锁才是权威判据，
        # 端口分支不再二次猜实例（否则自己跟自己撞）。
        log.warning("8777 被占用（孤儿服务/旧实例残留），清理后接管")
        _free_orphan_server()
        time.sleep(1.0)

    bridge.set_capture_handler(do_capture)
    start_server()  # 作为独立进程拉起 Web 服务（见 start_server）
    # 浏览器不等托盘：服务端口一通就开面板（后台线程，见 _open_browser_when_ready）
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    start_hotkey()
    # ⚠️ 2026-09-13：原来无条件调 start_wakeword()，config 里 enabled=false 时
    # 仍会构造检测器并打出 "wakeword listener started"（日志骗人，且白加载
    # librosa/numpy）。改为按开关走：关着就完全不启动（用户明确要求关）。
    if _wakeword_enabled():
        start_wakeword()
    else:
        log.info("wakeword off (config.wakeword.enabled=false)")
    ensure_notifier()
    threading.Thread(target=reminder_loop, daemon=True).start()
    threading.Thread(target=phone_watch_loop, daemon=True).start()
    threading.Thread(target=preload_stt, daemon=True).start()
    threading.Thread(target=diary_reminder_loop, daemon=True).start()
    threading.Thread(target=contact_todo_reminder_loop, daemon=True).start()
    threading.Thread(target=away_watch_loop, daemon=True).start()
    threading.Thread(target=transcribe_watch_loop, daemon=True).start()
    threading.Thread(target=readlater_loop, daemon=True).start()
    threading.Thread(target=birthday_reminder_loop, daemon=True).start()
    threading.Thread(target=backup_loop, daemon=True).start()
    threading.Thread(target=inbox_watch_loop, daemon=True).start()
    threading.Thread(target=course_reminder_loop, daemon=True).start()
    # msgdigest 采集循环已于 2026-09-18 按路河拍板下线（备份 .zcode_backup/2026-09-18_msgdigest下线/）

    # 关键：悬浮层/指示窗放到后台线程拉起。它们涉及 subprocess + 2s 等待，
    # 放主线程会拖慢托盘出现；一旦它们异常也不该拖死主程序（托盘/热键）。
    threading.Thread(target=_safe_ensure_overlay, daemon=True).start()
    threading.Thread(target=_safe_ensure_notifier, daemon=True).start()

    if HEADLESS:
        # 桌面壳模式：托盘图标由 desktop/shell.py 提供，这里不再建第二个图标。
        # 只保活——热键、录音、提醒、微信监视、8777 服务全部照旧在线。
        log.info("[headless] 托盘交给桌面壳；本进程保活（热键/服务在线）")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        stop_overlay()
        stop_notifier()
        log.info("[headless] 路远 stopped")
        return

    _tray_ok = True
    try:
        log.info("[诊断] 准备创建托盘图标")
        img = make_icon()
        import pystray
        icon = pystray.Icon("路远", icon=img, title="路远 · 语音记事",
                            menu=build_menu())
        try:
            if not _browser_opened:   # 后台线程已开过就不重复开（防两个标签页）
                open_browser()
        except Exception:
            pass
        log.info("路远 started")
        # 启动反馈（2026-09-13）：Windows 11 会把新托盘图标折叠进任务栏的
        # "^" 溢出区，用户常以为「没起来/没托盘」。给一条原生通知，
        # 明确告诉他去哪儿找（这是「不知道有没有成功」的正解）。
        try:
            native_toast("路远已启动", "托盘图标在屏幕右下角；看不到就点一下 ^ 展开。")
        except Exception:
            pass
        icon.run()
        stop_overlay()      # 托盘退出：收掉浮层（原先漏了，导致浮窗残留）
        stop_notifier()
        log.info("路远 stopped")
    except Exception as e:
        # 托盘创建/运行失败：Web 服务与热键已在前面启动，面板仍可用，
        # 把真实报错落盘，避免“静默死 + 无托盘 + 无日志”。
        _tray_ok = False
        log.exception("托盘创建/运行失败：%s", e)
        try:
            import traceback as _tb
            with open(os.path.join(BASE, "startup_error.log"), "w", encoding="utf-8") as _f:
                _f.write("路远托盘创建失败（Web 服务与热键仍在线）：\n\n")
                _tb.print_exc(file=_f)
        except Exception:
            pass
    if _tray_ok:
        # 托盘正常退出（用户从托盘菜单退出）：直接结束进程。
        return
    # 兜底保活：托盘没起来时主进程也不要退出——否则所有热键守护线程
    # 会随主进程一起被回收（表现为“没托盘 + 全部热键失灵”）。本循环让
    # 进程持续存活，热键/服务照常工作，直到用户手动结束进程。
    log.info("主进程进入保活（热键/服务持续在线，托盘未启用），等待退出信号")
    try:
        while True:
            time.sleep(3600)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback as _tb
        try:
            with open(os.path.join(BASE, "startup_error.log"), "w", encoding="utf-8") as _f:
                _f.write("路远主程序未捕获异常：\n\n")
                _tb.print_exc(file=_f)
        except Exception:
            pass
        raise
