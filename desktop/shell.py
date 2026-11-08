# -*- coding: utf-8 -*-
"""路远 · 桌面壳（Luyuan Desktop Shell）

把「浏览器 + bat + 多端口」收敛成一个独立软件窗口：
  · 原生 Win32 窗口 + WebView2 渲染（无地址栏 / 无标签页 / 无浏览器痕迹）
  · 单实例：重复双击 = 唤起已有窗口
  · 托盘常驻；关窗口 = 缩到托盘，后台服务与录音热键继续活着
  · 后台大脑交给 main.py --headless（热键 / 录音 / 提醒 / 微信监视全在那边）
  · 本地控制口 8781：供 main.py 的 F9 热键、外部脚本唤起窗口

架构：
    路远.exe (本文件, PyInstaller)  ── 管窗口 + 托盘 + 单实例
        └─ pythonw main.py --headless  ── 管后台逻辑（再拉起 server_runner 跑 8777）
    手机 App / Tailscale 仍直连 8777，壳退出不影响它们（除非在托盘里选「完全退出」）
"""
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP_NAME = "路远"
MUTEX_NAME = "Local\\LuYuanDesktopShell_v1"
CTRL_PORT = 8781
ICON_FILE = "路远.ico"

BASE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
LOG_PATH = os.path.join(BASE, "shell.log")


# ---------------------------------------------------------------- 基础设施
def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        print(line, end="", flush=True)
    except Exception:
        pass


def find_root(start=None):
    """向上找含 main.py + server_runner.py 的项目根（兼容 exe 放在 desktop/ 或 dist/ 下）。"""
    env = os.environ.get("LUYUAN_HOME")
    if env and os.path.isfile(os.path.join(env, "main.py")):
        return env
    cur = start or BASE
    for _ in range(5):
        if os.path.isfile(os.path.join(cur, "main.py")) and os.path.isfile(
            os.path.join(cur, "server_runner.py")
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.dirname(BASE)


ROOT = find_root()
STATE_PATH = os.path.join(BASE, "shell_state.json")


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass


def backend_python():
    """优先用项目 venv 的 pythonw.exe（无控制台窗口）。"""
    cands = [
        os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe"),
        os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
        sys.executable,
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return sys.executable


def port_open(port, host="127.0.0.1", timeout=0.35):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _hidden_flags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


# ---------------------------------------------------------------- 单实例
def acquire_single_instance():
    """返回 True = 我是第一个实例；False = 已有实例（并已通知它显示窗口）。"""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        h = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        err = kernel32.GetLastError()
        if err == 183:  # ERROR_ALREADY_EXISTS
            log("检测到已有壳实例，唤起窗口后退出")
            ctrl_request("/show")
            return False, h
        return True, h
    except Exception:
        log("互斥锁创建异常，按单实例继续：%s" % traceback.format_exc(limit=1))
        return True, None


def ctrl_request(path, timeout=1.5):
    try:
        s = socket.create_connection(("127.0.0.1", CTRL_PORT), timeout=timeout)
        s.sendall(
            ("GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" % path).encode()
        )
        data = s.recv(4096)
        s.close()
        return data.decode("utf-8", "ignore")
    except Exception:
        return ""


# ---------------------------------------------------------------- 后台大脑
class Backend:
    def __init__(self):
        self.proc = None

    def port(self):
        try:
            with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
                return int(json.load(f).get("server", {}).get("port", 8777))
        except Exception:
            return 8777

    def alive(self):
        return port_open(self.port())

    def ensure(self):
        """8777 没人监听时，拉起 main.py --headless；顺手带上 3927（路远远）看门狗。"""
        if self.alive():
            log("8777 已在监听，跳过拉起后台")
            return
        py = backend_python()
        cmd = [py, os.path.join(ROOT, "main.py"), "--headless"]
        log("拉起后台大脑：%s" % " ".join(cmd))
        env = dict(os.environ)
        env["LUYUAN_HEADLESS"] = "1"
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=ROOT, env=env, creationflags=_hidden_flags(), close_fds=True
            )
        except Exception:
            log("后台拉起失败：%s" % traceback.format_exc())

    def wait_ready(self, seconds=45):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.alive():
                return True
            time.sleep(0.25)
        return False

    def stop(self):
        """杀掉后台进程树（含 server_runner / uvicorn worker）。"""
        pid = self.proc.pid if self.proc and self.proc.poll() is None else None
        try:
            if os.name == "nt":
                args = ["taskkill", "/F", "/T"]
                if pid:
                    args += ["/PID", str(pid)]
                else:
                    # 兜底：扫 main.py --headless
                    args = [
                        "wmic", "process", "where",
                        "commandline like '%main.py%--headless%'", "call", "terminate",
                    ]
                subprocess.run(args, capture_output=True, timeout=8,
                               creationflags=_hidden_flags())
        except Exception:
            log("停止后台异常：%s" % traceback.format_exc(limit=1))
        # 再清 server_runner 残留
        try:
            subprocess.run(
                ["wmic", "process", "where", "commandline like '%server_runner.py%'",
                 "call", "terminate"],
                capture_output=True, timeout=8, creationflags=_hidden_flags())
        except Exception:
            pass


BACKEND = Backend()


# ---------------------------------------------------------------- 窗口
SPLASH = """<!doctype html><meta charset="utf-8">
<style>
  html,body{margin:0;height:100%;background:#F3EFE6;font-family:"Microsoft YaHei UI","Microsoft YaHei",sans-serif;
    display:flex;align-items:center;justify-content:center;color:#224A3A;user-select:none;-webkit-user-select:none}
  .box{text-align:center}
  .mark{font-size:34px;letter-spacing:.32em;font-weight:600;padding-left:.32em}
  .sub{margin-top:14px;font-size:13px;color:#7A7166;letter-spacing:.06em}
  .bar{margin:22px auto 0;width:150px;height:2px;background:#DCD3C3;overflow:hidden;border-radius:2px}
  .bar i{display:block;width:40%;height:100%;background:#224A3A;animation:run 1.2s ease-in-out infinite}
  @keyframes run{0%{transform:translateX(-100%)}100%{transform:translateX(320%)}}
</style>
<div class="box">
  <div class="mark">路 远</div>
  <div class="sub">正在唤醒工作台…</div>
  <div class="bar"><i></i></div>
</div>"""


class Shell:
    def __init__(self):
        self.window = None
        self.state = load_state()
        self.hidden = False
        self._quitting = False
        self.icon = None

    # ---- URL
    def panel_url(self):
        # 每次带时间戳：前端改了文件但 URL 不变时，WebView2 磁盘缓存会拿到旧脚本，
        # 出现过「改了没生效」的假象（2026-10-30 实测）。本地加载，禁用缓存无成本。
        return "http://127.0.0.1:%d/?embed=1&t=%d" % (BACKEND.port(), int(time.time()))

    def open_note(self, nid):
        """从通知/热键跳转到某条笔记（沿用前端已有的 #n=<id> 锚点）。"""
        try:
            self.window.load_url(self.panel_url() + "#n=" + str(nid))
        except Exception:
            log("open_note 失败：%s" % traceback.format_exc(limit=1))

    # ---- 窗口事件
    def on_loaded(self):
        if not getattr(self, "_icon_done", False):
            self.apply_window_icon()   # native Form 只有在 loaded 之后才存在
            self._icon_done = True
        try:
            self.window.evaluate_js(HARDEN_JS)
        except Exception:
            log("注入 JS 失败：%s" % traceback.format_exc(limit=1))
        log("页面已加载")

    def on_closing(self):
        if self._quitting:
            return True
        self.hide()
        return False

    def on_moved(self, x=None, y=None):
        try:
            self.state["x"], self.state["y"] = int(x), int(y)
            save_state(self.state)
        except Exception:
            pass

    def on_resized(self, w=None, h=None):
        try:
            if getattr(self.window, "maximized", False):
                self.state["maximized"] = True
                save_state(self.state)
                return
            if w and h and int(w) >= 400 and int(h) >= 300:
                self.state["w"], self.state["h"] = int(w), int(h)
                self.state["maximized"] = False
                save_state(self.state)
        except Exception:
            pass

    # ---- 显隐
    def show(self):
        try:
            if self.window:
                self.window.show()
                self.window.restore()
                self.window.on_top = True
                self.window.on_top = False
                self.hidden = False
        except Exception:
            log("show 失败：%s" % traceback.format_exc(limit=1))

    def hide(self):
        try:
            if self.window:
                self.window.hide()
                self.hidden = True
        except Exception:
            log("hide 失败：%s" % traceback.format_exc(limit=1))

    def toggle(self):
        if self.hidden:
            self.show()
        else:
            self.hide()

    def apply_window_icon(self):
        """把标题栏/任务栏图标换成路远自己的 .ico（默认是 python 蓝点）。"""
        p = os.path.join(BASE, ICON_FILE)
        if not os.path.isfile(p):
            p = os.path.join(ROOT, ICON_FILE)
        if not os.path.isfile(p):
            log("未找到 %s，跳过图标" % ICON_FILE)
            return
        try:
            import clr

            clr.AddReference("System.Drawing")
            from System.Drawing import Icon as _Icon  # noqa

            form = self.window.native
            form.Icon = _Icon(p)
            log("窗口图标已设置 %s" % p)
        except Exception:
            log("设置窗口图标失败：%s" % traceback.format_exc(limit=1))

    def notify_hidden(self):
        """第一次缩到托盘时给一条提示，避免用户以为关掉了。"""
        if self.state.get("tray_hinted"):
            return
        try:
            if self.icon:
                self.icon.notify("路远还在后台跑", "点托盘图标可重新打开；要彻底退出用托盘菜单")
                self.state["tray_hinted"] = True
                save_state(self.state)
        except Exception:
            pass

    # ---- 启动流程（在 webview.start 的回调线程里跑）
    def boot(self):
        # 1. 后台没起就起
        BACKEND.ensure()
        ok = BACKEND.wait_ready(45)
        log("后台就绪=%s" % ok)
        # 2. 切到真实面板
        if ok:
            try:
                self.window.load_url(self.panel_url())
            except Exception:
                log("load_url 失败：%s" % traceback.format_exc(limit=1))
        else:
            try:
                self.window.load_html(
                    "<body style='background:#F3EFE6;font-family:Microsoft YaHei;padding:48px;color:#8C2F27'>"
                    "<h2>工作台没能起来</h2><p>后台服务 45 秒内没监听端口。日志：<code>%s</code></p>"
                    "<p>可在托盘菜单里点「重启后台服务」。</p></body>" % ROOT
                )
            except Exception:
                pass
        # 2.5 窗口尺寸：DPI 感知后窗口按物理像素算，175% 缩放下 1320px 只有 754 CSS 宽，
        #     页面会被挤成手机版 → 默认铺满工作区（用户手动改过窗口大小才尊重记录值）。
        #     ⚠️ 不用 window.maximize()：WinForms 在 PerMonitorV2 下会把窗口铺到整屏、
        #     盖掉任务栏（2026-10-30 实测）。改用工作区矩形精确摆放。
        if self.state.get("maximized", True):
            self.fill_workarea()

    def fill_workarea(self):
        try:
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            r = wintypes.RECT()
            if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
                raise OSError("SPI_GETWORKAREA failed")
            w, h = r.right - r.left, r.bottom - r.top
            hwnd = int(self.window.native.Handle.ToInt64())
            SWP_SHOWWINDOW = 0x0040
            SWP_NOZORDER = 0x0004
            user32.SetWindowPos(hwnd, 0, r.left, r.top, w, h, SWP_NOZORDER | SWP_SHOWWINDOW)
            log("窗口铺满工作区 %dx%d @ (%d,%d)" % (w, h, r.left, r.top))
        except Exception:
            log("fill_workarea 失败：%s" % traceback.format_exc(limit=2))
        # 3. 托盘
        threading.Thread(target=self.start_tray, daemon=True).start()

    # ---- 托盘
    def tray_image(self):
        try:
            from PIL import Image

            p = os.path.join(BASE, ICON_FILE)
            if not os.path.isfile(p):
                p = os.path.join(ROOT, ICON_FILE)
            if os.path.isfile(p):
                return Image.open(p)
        except Exception:
            pass
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([2, 2, 61, 61], radius=14, fill=(243, 239, 230, 255),
                            outline=(34, 74, 58, 255), width=3)
        d.text((16, 18), "路", fill=(34, 74, 58, 255))
        return img

    def start_tray(self):
        try:
            import pystray
        except Exception:
            log("pystray 不可用，跳过托盘：%s" % traceback.format_exc(limit=1))
            return
        from pystray import Menu, MenuItem

        def rec():
            try:
                subprocess.Popen(
                    [backend_python(), "-c",
                     "import urllib.request;urllib.request.urlopen("
                     "'http://127.0.0.1:%d/api/capture',data=b'{}',timeout=3)" % BACKEND.port()],
                    cwd=ROOT, creationflags=_hidden_flags())
            except Exception:
                pass

        def restart():
            log("托盘：重启后台")
            BACKEND.stop()
            time.sleep(1.2)
            BACKEND.ensure()

        def open_dir():
            try:
                os.startfile(os.path.join(ROOT, "data"))
            except Exception:
                pass

        def quit_all():
            self._quitting = True
            log("托盘：完全退出")
            try:
                self.icon.stop()
            except Exception:
                pass
            BACKEND.stop()
            try:
                self.window.destroy()
            except Exception:
                pass

        menu = Menu(
            MenuItem("打开路远", lambda i, it: self.show(), default=True),
            MenuItem("现在记一条（F10）", lambda i, it: rec()),
            Menu.SEPARATOR,
            MenuItem("重启后台服务", lambda i, it: threading.Thread(target=restart, daemon=True).start()),
            MenuItem("打开数据目录", lambda i, it: open_dir()),
            Menu.SEPARATOR,
            MenuItem("完全退出（含后台）", lambda i, it: quit_all()),
        )
        try:
            self.icon = pystray.Icon(APP_NAME, icon=self.tray_image(),
                                     title="路远 · 语音记事", menu=menu)
            self.icon.run_detached()
            log("托盘已就绪")
        except Exception:
            log("托盘启动失败：%s" % traceback.format_exc())


HARDEN_JS = r"""
(function(){
  if (window.__lyShell) return; window.__lyShell = 1;
  // 屏蔽浏览器痕迹：右键菜单 / F5刷新 / F12 / Ctrl+P / Ctrl+S / Ctrl+U
  document.addEventListener('contextmenu', function(e){
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    e.preventDefault();
  }, true);
  document.addEventListener('keydown', function(e){
    var k = (e.key || '').toLowerCase();
    var inField = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable);
    if (k === 'f5' || k === 'f12' || k === 'f7') { e.preventDefault(); return; }
    if (e.ctrlKey && !e.shiftKey && !inField && ['p','s','u','o'].indexOf(k) >= 0) { e.preventDefault(); }
    if (e.ctrlKey && e.shiftKey && ['i','j','c'].indexOf(k) >= 0) { e.preventDefault(); }
  }, true);
  // 拖入文件不再触发浏览器「打开/下载」
  window.addEventListener('dragover', function(e){ e.preventDefault(); }, false);
  window.addEventListener('drop', function(e){
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) return; // 页面自己处理
    e.preventDefault();
  }, false);
})();
"""


# ---------------------------------------------------------------- 控制口
class CtrlHandler(BaseHTTPRequestHandler):
    shell = None

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)
        sh = CtrlHandler.shell
        try:
            if p == "/show":
                nid = (q.get("nid") or [""])[0]
                if nid:
                    sh.open_note(nid)
                sh.show()
                return self._send({"ok": True, "action": "show", "nid": nid})
            if p == "/hide":
                sh.hide()
                return self._send({"ok": True, "action": "hide"})
            if p == "/toggle":
                sh.toggle()
                return self._send({"ok": True, "action": "toggle"})
            if p == "/open":
                page = (q.get("page") or [""])[0]
                sh.show()
                if page:
                    sh.window.evaluate_js(
                        "try{window.LY&&window.LY.go&&window.LY.go(%s)}catch(e){}" %
                        json.dumps(page))
                return self._send({"ok": True, "page": page})
            if p == "/reload":
                sh.window.load_url(sh.panel_url())
                return self._send({"ok": True, "action": "reload"})
            if p == "/eval":
                expr = (q.get("js") or [""])[0]
                if not expr:
                    return self._send({"ok": False, "err": "missing js"})
                try:
                    val = sh.window.evaluate_js(expr)
                except Exception as e:
                    val = "ERR: %s" % e
                return self._send({"ok": True, "value": val})
            if p == "/openurl":
                # 只放行本机回环地址：这是给「打开路远远管理面板(3927)」这类入口用的，
                # 不能让界面上的任意链接变成"用系统默认程序打开任何 URL"的口子。
                url = (q.get("u") or [""])[0]
                try:
                    pu = urlparse(url)
                    ok_host = pu.scheme in ("http", "https") and pu.hostname in (
                        "127.0.0.1", "localhost", "::1")
                except Exception:
                    ok_host = False
                if not ok_host:
                    return self._send({"ok": False, "err": "only local url allowed"}, 403)
                try:
                    os.startfile(url)
                    return self._send({"ok": True, "url": url})
                except Exception as e:
                    return self._send({"ok": False, "err": str(e)}, 500)
            if p == "/quit":
                sh._quitting = True
                threading.Thread(target=lambda: (BACKEND.stop(), os._exit(0)), daemon=True).start()
                return self._send({"ok": True})
            if p == "/status":
                return self._send({
                    "ok": True, "hidden": sh.hidden, "backend": BACKEND.alive(),
                    "port": BACKEND.port(), "root": ROOT,
                })
            return self._send({"ok": False, "err": "unknown"}, 404)
        except Exception:
            return self._send({"ok": False, "err": traceback.format_exc(limit=2)}, 500)


def start_ctrl_server(shell):
    CtrlHandler.shell = shell
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", CTRL_PORT), CtrlHandler)
    except OSError:
        log("控制口 %d 被占用，跳过（不影响窗口）" % CTRL_PORT)
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log("控制口已就绪 http://127.0.0.1:%d" % CTRL_PORT)
    return srv


# ---------------------------------------------------------------- 安装/自启
def _launch_cmd():
    """返回 (目标 exe, 参数串)。打包后是自身；源码运行时退回 venv 的 pythonw。"""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pyw = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    return pyw, '"%s"' % os.path.join(BASE, "shell.py")


def install_shortcuts():
    """桌面快捷方式 + 开机自启（HKCU Run）。用 win32com 建 lnk，无窗口闪烁。"""
    exe, args = _launch_cmd()
    icon = os.path.join(BASE, ICON_FILE)
    if not os.path.isfile(icon):
        icon = os.path.join(ROOT, ICON_FILE)
    made = []
    try:
        import win32com.client

        sh = win32com.client.Dispatch("WScript.Shell")
        desktop = sh.SpecialFolders("Desktop")
        lnk = os.path.join(desktop, "路远.lnk")
        s = sh.CreateShortCut(lnk)
        s.TargetPath = exe
        s.Arguments = args
        s.WorkingDirectory = BASE
        s.IconLocation = icon
        s.Description = "路远 · 语音记事工作台"
        s.Save()
        made.append(lnk)
    except Exception:
        log("桌面快捷方式失败：%s" % traceback.format_exc(limit=2))
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        cmd = ('"%s" %s --tray' % (exe, args)).strip()
        winreg.SetValueEx(key, "LuyuanShell", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        made.append("HKCU\\Run\\LuyuanShell = " + cmd)
    except Exception:
        log("开机自启写入失败：%s" % traceback.format_exc(limit=2))
    return made


def uninstall_shortcuts():
    out = []
    try:
        import win32com.client

        sh = win32com.client.Dispatch("WScript.Shell")
        lnk = os.path.join(sh.SpecialFolders("Desktop"), "路远.lnk")
        if os.path.isfile(lnk):
            os.remove(lnk)
            out.append("removed " + lnk)
    except Exception:
        pass
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "LuyuanShell")
        winreg.CloseKey(key)
        out.append("removed HKCU\\Run\\LuyuanShell")
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- 入口
def main():
    log("=" * 60)
    log("壳启动 pid=%s frozen=%s root=%s" % (os.getpid(), getattr(sys, "frozen", False), ROOT))
    # DPI 感知（exe 已带 PerMonitorV2 manifest；python 直跑时靠这里兜底，
    # 否则 175% 缩放下 WebView2 位图被系统整体拉伸 → 页面按 1477 排版再放大 1.8 倍被裁）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        log("DPI awareness: shcore ok")
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            log("DPI awareness: user32 fallback ok")
        except Exception:
            log("DPI awareness: 设置失败（继续）")

    if "--install" in sys.argv:
        for x in install_shortcuts():
            log("install: " + str(x))
        print("安装完成：", *install_shortcuts(), sep="\n  ")
        return
    if "--uninstall" in sys.argv:
        for x in uninstall_shortcuts():
            log("uninstall: " + str(x))
        return

    first, mutex = acquire_single_instance()
    if not first:
        return

    import webview

    shell = Shell()
    st = shell.state
    hide_at_start = "--tray" in sys.argv or "--hidden" in sys.argv
    shell.window = webview.create_window(
        APP_NAME,
        html=SPLASH,
        width=int(st.get("w", 1320)),
        height=int(st.get("h", 880)),
        x=st.get("x"),
        y=st.get("y"),
        minimized=False,
        hidden=hide_at_start,
        maximized=bool(st.get("maximized", True)),
        min_size=(1000, 640),
        background_color="#F3EFE6",
        confirm_close=False,
        text_select=True,
        easy_drag=False,
    )
    shell.hidden = hide_at_start
    shell.window.events.loaded += shell.on_loaded
    shell.window.events.closing += shell.on_closing
    shell.window.events.moved += shell.on_moved
    shell.window.events.resized += shell.on_resized

    start_ctrl_server(shell)

    icon = os.path.join(BASE, ICON_FILE)
    if not os.path.isfile(icon):
        icon = os.path.join(ROOT, ICON_FILE)

    try:
        webview.start(
            shell.boot,
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=os.path.join(BASE, ".webview"),
            icon=icon if os.path.isfile(icon) else None,
        )
    except Exception:
        log("webview.start 异常：%s" % traceback.format_exc())
        raise
    finally:
        log("壳退出")
        if not shell._quitting:
            BACKEND.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("未捕获异常：%s" % traceback.format_exc())
        raise