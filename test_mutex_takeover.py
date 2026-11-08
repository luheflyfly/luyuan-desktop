"""验证「等旧实例退净再接管」逻辑（不动线上实例：用独立的测试锁名）。"""
import io
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Luyuan")
os.chdir(r"D:\Luyuan")
import main  # noqa: E402

PY = r"D:\Luyuan\.venv\Scripts\python.exe"
NAME = "Local\\LuyuanTestMutex_" + str(os.getpid())

HOLDER_SRC = r'''
import ctypes, sys, time
k = ctypes.WinDLL("kernel32.dll", use_last_error=True)
k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
k.CreateMutexW.restype = ctypes.c_void_p
h = k.CreateMutexW(None, 0, sys.argv[1])
print("held", flush=True)
time.sleep(float(sys.argv[2]))
'''

main._MAIN_MUTEX_NAME = NAME
results = []


def check(label, cond, extra=""):
    results.append(bool(cond))
    print(("  PASS " if cond else "  FAIL ") + label + ("  " + extra if extra else ""))


def release_ours():
    import ctypes
    if main._MAIN_MUTEX:
        ctypes.WinDLL("kernel32.dll").CloseHandle(main._MAIN_MUTEX)
        main._MAIN_MUTEX = None


def spawn_holder(seconds):
    p = subprocess.Popen([PY, "-c", HOLDER_SRC, NAME, str(seconds)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    p.stdout.readline()          # 等它真正拿到锁
    return p


print("== A 无人持锁 → 立即接管 ==")
t0 = time.time()
r = main._try_take_over_mutex(max_wait=3, poll=0.3)
el = time.time() - t0
check("返回 ok 且耗时 < 1s", r == "ok" and el < 1.0, "r=%s %.2fs" % (r, el))
release_ours()

print("== B 持有者健在 + 8777 有服务 → 立刻让位 ==")
main._server_alive = lambda timeout=0.6: True
hb = spawn_holder(6)
t0 = time.time()
r = main._try_take_over_mutex(max_wait=5, poll=0.3)
el = time.time() - t0
check("返回 taken 且耗时 < 1s（不白等）", r == "taken" and el < 1.0, "r=%s %.2fs" % (r, el))
release_ours()
hb.wait(timeout=12)              # 必须等它退，否则它的锁会串到下一个用例

print("== C 持有者收尾中(2.5s后退出) + 8777 无服务 → 等锁释放后接管 ==")
main._server_alive = lambda timeout=0.6: False
h = spawn_holder(2.5)
t0 = time.time()
r = main._try_take_over_mutex(max_wait=8, poll=0.5)
el = time.time() - t0
check("返回 ok 且耗时在 2~5s（等到旧实例退净）", r == "ok" and 1.5 <= el <= 5.5,
      "r=%s %.2fs" % (r, el))
release_ours()
h.wait(timeout=6)

print("== D 持有者赖着不走 + 8777 无服务 → 等满上限后保守让位 ==")
h = spawn_holder(8)
t0 = time.time()
r = main._try_take_over_mutex(max_wait=2, poll=0.5)
el = time.time() - t0
check("返回 taken 且耗时在 2~3.5s", r == "taken" and 1.8 <= el <= 3.5, "r=%s %.2fs" % (r, el))
release_ours()
h.wait(timeout=10)

print("== E 真实锁名未被测试污染 ==")
import ctypes  # noqa: E402
k = ctypes.WinDLL("kernel32.dll", use_last_error=True)
k.OpenMutexW.restype = ctypes.c_void_p
hh = k.OpenMutexW(0x00100000, False, "Local\\LuyuanMainKernel")
check("线上锁仍在（说明本轮测试没碰它）", bool(hh), "handle=%s" % hh)

print()
print("结果：%d/%d 通过" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
