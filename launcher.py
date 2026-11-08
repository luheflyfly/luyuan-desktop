"""路远启动器：保证单实例 + 自动清理僵尸进程 + 启动结果可见（成功/失败都弹窗）。
由 run_hidden.vbs 以隐藏方式调用；本文件不直接做托盘，而是用子进程拉起 main.py。
"""
import os
import sys
import subprocess
import time
import urllib.request
import webbrowser
import ctypes
import threading
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def _box(msg, kind=0x40, auto_close_ms=None):
    """弹窗。kind: 0x40=信息, 0x10=错误, 0x30=警告。
    auto_close_ms 非 None 时，N 毫秒后自动关闭（用户可提前点确定关闭）。"""
    try:
        if auto_close_ms:
            def _close_later():
                time.sleep(auto_close_ms / 1000.0)
                try:
                    hwnd = ctypes.windll.user32.FindWindowW(None, "路远")
                    if hwnd:
                        WM_CLOSE = 0x10
                        ctypes.windll.user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
                except Exception:
                    pass
            threading.Thread(target=_close_later, daemon=True).start()
        ctypes.windll.user32.MessageBoxW(0, str(msg), "路远", kind)
    except Exception:
        pass


def show_info(msg, auto_close_ms=None):
    _box(msg, 0x40, auto_close_ms=auto_close_ms)


def show_error(msg):
    _box(msg, 0x10)


def log_path():
    return os.path.join(BASE, "startup_error.log")


def port_pid(port):
    """返回占用 port 的 LISTENING 进程 PID，没有则返回 None。"""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL,
            encoding="gbk", errors="ignore", timeout=10
        )
    except Exception:
        return None
    if not out:
        return None
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 5 and (":%d" % port) in cols[1] and cols[3] == "LISTENING":
            pid = cols[4]
            if pid.isdigit():
                return int(pid)
    return None


def _proc_name(pid):
    """尽力拿到进程 exe 名（如 python.exe）；任何查询失败都返回 ''，绝不抛异常。
    注意 tasklist /fo csv 首行是表头（映像名称），需取末行数据并跳过表头。"""
    for cmd in (
        ["tasklist", "/fi", "pid eq %d" % pid, "/fo", "csv"],
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').Name" % pid],
    ):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                          encoding="gbk", errors="ignore", timeout=10).strip()
            if not out:
                continue
            lines = [l for l in out.splitlines() if l.strip()]
            row = lines[-1] if len(lines) > 1 else lines[0]
            name = row.split(",")[0].strip('"')
            if name and name != "映像名称":   # 跳过表头
                return name
        except Exception:
            continue
    return ""


def _free_port_python(port):
    """释放 port 上任何 LISTENING 的 python 进程（我们的旧服务 / 诊断 uvicorn 等）。
    仅杀 python* 进程，避免误杀其他程序；清场阶段调用（此时不应有合法路远在跑）。
    进程名查询失败时（沙箱等）按“兜底杀”处理，避免残留进程赖着端口导致起不来。"""
    pid = port_pid(port)
    if not pid:
        return
    name = _proc_name(pid)
    nl = name.lower()
    if "python" in nl or nl == "":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass


def is_alive(url):
    try:
        urllib.request.urlopen(url + "/api/health", timeout=2)
        return True
    except Exception:
        return False


def _main_count():
    """当前有多少个 main.py 进程。异常返回 0。"""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*<project-root>\\main.py*' } | "
             "Measure-Object | Select-Object -ExpandProperty Count"],
            stderr=subprocess.DEVNULL, encoding="gbk", errors="ignore", timeout=10)
        t = out.strip()
        return int(t) if t.isdigit() else 0
    except Exception:
        return 0


def main_alive():
    """是否有活的路远主进程（带托盘/热键的 main.py）在跑。

    只查 main.py 进程本身，不查 8777 端口——因为 server_runner 是独立进程，
    主进程死了它还会占着端口，单看端口会误判“已运行”而直接退出，留下死实例。

    ⚠️ 2026-09-13：命中后 1.5s 二次确认——旧实例退出时会有一段「进程尚未死」
    的尾巴，此时直接判「已在运行」会让新启动直接放弃（用户实测：双击后没托盘）。
    """
    if _main_count() <= 0:
        return False
    time.sleep(1.5)
    return _main_count() > 0


def cmdline_of(pid):
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid],
            stderr=subprocess.DEVNULL, encoding="gbk", errors="ignore", timeout=10)
        return out.strip()
    except Exception:
        return ""


def open_browser(url):
    """比 webbrowser 模块更可靠地用默认浏览器打开（绕过隐藏窗口限制）。"""
    try:
        os.startfile(url)          # Windows ShellExecute，隐藏进程也能弹
        return True
    except Exception:
        pass
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def start_main():
    py = os.path.join(BASE, ".venv", "Scripts", "python.exe")
    script = os.path.join(BASE, "main.py")
    # CREATE_NO_WINDOW: 子进程不弹黑窗，但托盘/日志正常
    # stderr/stdout 追加落盘（2026-09-08 深夜）：此前 DEVNULL 把原生崩溃现场
    # 全吞了（剪贴板段错误案就是因此瞎排查几小时）。存 data/main_console.log。
    try:
        out = open(os.path.join(BASE, "data", "main_console.log"), "ab")
    except Exception:
        out = subprocess.DEVNULL
    return subprocess.Popen(
        [py, script],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=out, stderr=out,
    )


def main_launch():
    # 单 launcher 互斥锁：避免连点 bat 导致多个 launcher 并发清场/启动，
    # 互相杀掉对方拉起的 main 进程（表现为“启动后热键全失效 / 进程早死”）。
    _lock = os.path.join(BASE, "startup.lock")
    _lfd = None
    try:
        if os.path.exists(_lock) and (time.time() - os.path.getmtime(_lock)) > 60:
            os.remove(_lock)   # 残留的陈旧锁（上次异常退出未清理）直接清掉
    except Exception:
        pass
    try:
        _lfd = os.open(_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # 锁存在：可能是另一个 launcher 正在启动，也可能是陈旧锁残留。
        # 必须确认主进程是否真活着——活着才只开面板；主进程已死要清锁重启，
        # 否则会卡在“打开浏览器但路远没起来”的死状态（表现为没托盘+热键全死）。
        if main_alive():
            open_browser("http://127.0.0.1:8777")
            show_info("路远已在运行，已为你打开面板。", auto_close_ms=2500)
        else:
            try:
                os.remove(_lock)
            except Exception:
                pass
            _launch_inner()   # 锁已清，重新走完整启动流程（会再建锁）
        return
    try:
        _launch_inner()
    finally:
        try:
            if _lfd is not None:
                os.close(_lfd)
            os.remove(_lock)
        except Exception:
            pass


def _launch_inner():
    # 0. 依赖自检（缺库时给明确提示，而不是静默崩）
    # 优化（2026-09-11）：改用 find_spec 只查「包在不在」，不真正执行模块代码——
    # 真 import sounddevice/pynput 等每次多花 ~1s，而这里只需要缺没缺。
    import importlib.util
    _missing = [m for m in ("fastapi", "uvicorn", "pystray", "pynput", "sounddevice")
                if importlib.util.find_spec(m) is None]
    if _missing:
        show_error("路远依赖缺失：%s\n请确认 <project-root>\\.venv 完整，或联系助手修复。"
                   % ", ".join(_missing))
        return

    import config
    cfg = config.load()["server"]
    port = cfg["port"]
    # 本地自检/打开一律走 127.0.0.1（服务虽绑定 0.0.0.0 以允许手机访问）
    url = "http://127.0.0.1:%d" % port

    # 0.4 单实例智能判断：主进程（带托盘/热键的 main.py）还活着就只开面板，
    # 绝不杀正在运行的实例（避免把正常实例误杀成“无托盘+无热键”）。
    # 注意：不能只看 8777 端口——server_runner 是独立进程，主进程死了它仍占端口，
    # 会误判“已运行”而退出，留下死实例。所以这里查 main.py 进程本身。
    if main_alive():
        open_browser(url)
        show_info("路远已在运行，已为你打开面板。", auto_close_ms=2500)
        return

    # 0.5 清场（按需，2026-09-11 优化）：先快速探测端口，端口空着就跳过
    # PowerShell 清场——冷启动没残留时原先每次白跑 ~1.5s（PowerShell 查询 + sleep）。
    # main_alive() 为 False + 端口空闲 → 没有任何东西挡路，直接进启动；
    # 残留孤儿场景（端口被占）走完整清理。main.py 自身还有内核互斥锁 +
    # 端口探测双兜底，孤儿/双开不会失控。
    if port_pid(port):
        try:
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*<project-root>\\main.py*' -or "
                  "$_.CommandLine -like '*<project-root>\\server_runner.py*' -or "
                  "$_.CommandLine -like '*<project-root>\\overlay.py*' -or "
                  "$_.CommandLine -like '*<project-root>\\notifier.py*' -or "
                  "$_.CommandLine -like '*<project-root>\\quicknote.py*' } | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           stderr=subprocess.DEVNULL, timeout=15)
            _free_port_python(port)   # 兜底：按端口杀掉任何赖在 8777 的 python 进程
            time.sleep(0.3)           # taskkill /F 同步完成，短等让内核释放端口即可
        except Exception:
            pass

    # 1. 端口处理：0.5 清场后若 8777 仍被占用，直接按端口释放。
    #    任何 python* 进程（我们的旧服务 / 诊断 uvicorn）一律杀掉；进程名查不到时
    #    兜底杀（沙箱查询可能失败），只有明确是外部非 python 程序才报错退出。
    pid = port_pid(port)
    if pid:
        name = _proc_name(pid)
        nl = name.lower()
        if "python" in nl or nl == "":
            # 我们的旧服务 / 诊断 uvicorn / 查询失败兜底 → 杀掉，确保新代码加载
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               stderr=subprocess.DEVNULL, timeout=10)
            except Exception:
                pass
            time.sleep(0.5)       # /F 同步杀完，短等端口释放即可（原 1.5s）
        else:
            show_error("端口 %d 被其他程序（非路远，PID %d：%s）占用，路远无法启动。\n"
                       "请先关闭占用该端口的程序，或联系助手换端口。" % (port, pid, name))
            return

    # 2. 启动子进程
    proc = start_main()

    # 3. 等待就绪（最多 30s），并给可见反馈
    #    成功判定必须「端口活着 且 主进程(main.py)也活着」同时成立——
    #    只查端口会中招：server_runner 是独立进程，主进程死了它仍占 8777，
    #    此时 is_alive 仍为 True 但托盘/热键全死，误报“启动成功”。
    #    优化（2026-09-11）：轮询加密到 0.3s；main_alive()（PowerShell，~0.3s）
    #    只在端口已通后才查——原先每轮都查，纯拖时间。
    for i in range(100):
        time.sleep(0.3)
        if is_alive(url) and main_alive():
            # 浏览器交给 main.py 自动打开，这里不再重复开（避免双标签页）
            show_info("路远已启动 ✅\n托盘图标在屏幕右下角，左键单击即可打开面板。\n"
                      "面板地址：%s\n\n（3 秒后自动关闭，点击确定立即关闭）" % url,
                      auto_close_ms=3000)
            return
        if proc.poll() is not None:
            # 子进程提前退出 = 崩溃
            break

    # 若主程序把崩溃 traceback 落盘了，直接读出来给用户看（免去翻文件）
    _detail = ""
    try:
        _se = log_path()
        if os.path.exists(_se):
            with open(_se, "r", encoding="utf-8", errors="ignore") as _fh:
                _detail = _fh.read().strip()
    except Exception:
        _detail = ""
    if _detail:
        show_error("路远启动失败（主程序崩溃）。\n\n错误详情：\n%s\n\n"
                   "请把这段内容发给我即可定位。\n日志：%s" %
                   (_detail[:1500], os.path.join(BASE, "data", "luyuan.log")))
    else:
        show_error("路远启动超时或子进程崩溃。\n"
                   "请查看日志：\n  - %s\n  - %s\n并把内容发给我定位。" %
                   (os.path.join(BASE, "data", "luyuan.log"), log_path()))


if __name__ == "__main__":
    try:
        main_launch()
    except Exception as e:
        tb = traceback.format_exc()
        try:
            with open(log_path(), "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        show_error("路远启动出现异常，错误详情已记录到：\n%s\n\n%s" % (log_path(), e))
