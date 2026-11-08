r"""探测天禧键/任意键实际发出的键盘码。

用法：双击「识别天禧按键.bat」→ 按提示按下那个键 → 本窗口会显示识别结果，
同时写入 D:\Luyuan\data\probe_result.txt（供 zcode 读取后绑定热键）。
按 Esc 结束探测。
"""
import os
import time

from pynput import keyboard

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "data", "probe_result.txt")

lines = []
count = {"n": 0}


def fmt(key):
    try:
        return key.char
    except AttributeError:
        return str(key)


def on_press(key):
    name = fmt(key)
    lines.append(time.strftime("%H:%M:%S") + "  PRESS: " + name)
    count["n"] += 1
    print("\n[%d] 捕获到按键: %s" % (count["n"], name))
    print("（继续按几次没关系；按 Esc 结束探测）")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def on_release(key):
    if key == keyboard.Key.esc:
        print("\n探测结束，结果在", OUT)
        return False


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print("=" * 50)
    print("按键探测中…")
    print("请现在按下你要测试的键（比如联想天禧键）2-3 次。")
    print("本窗口会显示每个键对应的键盘码。按 Esc 结束。")
    print("=" * 50)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
    print("完成。按回车关闭窗口…")
    input()
