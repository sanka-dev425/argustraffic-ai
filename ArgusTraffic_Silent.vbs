Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

venvPythonw = currentDir & "\.venv\Scripts\pythonw.exe"
sysPythonw = "C:\Python314\pythonw.exe"
appScript = currentDir & "\desktop_app.py"

If fso.FileExists(venvPythonw) Then
    WshShell.Run """" & venvPythonw & """ """ & appScript & """", 0, False
ElseIf fso.FileExists(sysPythonw) Then
    WshShell.Run """" & sysPythonw & """ """ & appScript & """", 0, False
Else
    WshShell.Run "pythonw """ & appScript & """", 0, False
End If
