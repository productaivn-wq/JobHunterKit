Set Args = WScript.Arguments
If Args.Count = 0 Then
    WScript.Quit
End If

cmd = ""
For i = 0 To Args.Count - 1
    arg = Args(i)
    If InStr(arg, " ") > 0 Then
        arg = """" & arg & """"
    End If
    If i = 0 Then
        cmd = arg
    Else
        cmd = cmd & " " & arg
    End If
Next

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run cmd, 0, True
