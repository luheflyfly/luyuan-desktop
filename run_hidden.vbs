Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
py = base & "\.venv\Scripts\python.exe"
script = base & "\launcher.py"
ws.Run """" & py & """ """ & script & """", 0, False
