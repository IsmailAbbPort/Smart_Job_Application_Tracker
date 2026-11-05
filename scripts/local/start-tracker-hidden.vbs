' Runs start-tracker.cmd with no console window, passing its arguments through.
' Used by the logon task: a scheduled task that runs cmd.exe directly flashes a
' console on the desktop every single boot.
Dim shell, fso, here, args, i
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " " & WScript.Arguments(i)
Next
shell.Run """" & here & "\start-tracker.cmd""" & args, 0, False
