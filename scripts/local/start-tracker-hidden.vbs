' Runs start-tracker.cmd with no console window, passing its arguments through.
' Used by the logon task: a scheduled task that runs cmd.exe directly flashes a
' console on the desktop every single boot.
'
' Waits for the launcher and exits with its code. Firing and forgetting made the
' task's Last Run Result 0x0 whether the stack came up or not, so Task Scheduler
' (the one place you would look) reported success for every failure.
Dim shell, fso, here, args, i, rc
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " " & WScript.Arguments(i)
Next
rc = shell.Run("""" & here & "\start-tracker.cmd""" & args, 0, True)
WScript.Quit rc
