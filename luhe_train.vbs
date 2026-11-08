Set ws = CreateObject("WScript.Shell")
local = ws.ExpandEnvironmentStrings("%LOCALAPPDATA%")
py = local & "\Microsoft\WindowsApps\python3.exe"
ws.CurrentDirectory = "D:\Luyuan"
ws.Run """" & py & """ ""D:\Luyuan\train_gui.py""", 0, False
