' Runs scripts\demo-watch.ps1 without a console window (Task Scheduler starts this every 5 minutes).
' Keep this file ASCII only: the folder path is read at run time.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = fso.GetParentFolderName(folder)
shell.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & folder & "\demo-watch.ps1""", 0, False
