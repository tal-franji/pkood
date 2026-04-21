Set Shell zsh
Set CursorBlink false
Output pkood_gemini.mp4
Type "echo Start a Gemini session that monitors all other sessions."
Enter
Sleep 2s
Type "pkood start --name monitor "
Sleep 200ms
Type "--cmd gemini"
Sleep 200ms
Enter
Wait
Escape
Type "[?1;2c"
Escape
Type "[>1;95;0c"
Sleep 500ms
Type "# (a comment) Use /pkood:start skill to start other Gemini sessions. define what you want in free language"
Enter
Sleep 1s
Type "/pkood:start "
Sleep 200ms
Type "run "
Sleep 200ms
Type "mypy on the"
Sleep 200ms
Type " tellem project files"
Sleep 200ms
Enter
Sleep 6s
Escape
Type "OB"
Enter
Sleep 5s
Escape
Type "OB"
Enter
Sleep 2s
Escape
Type "OB"
Sleep 500ms
Enter
Sleep 3.5s
Escape
Type "OB"
Sleep 500ms
Enter
Sleep 5.5s
Escape
Type "OB"
Sleep 500ms
Enter
Sleep 18s
Type "/pkood:start "
Sleep 200ms
Type "run flake8 on the "
Sleep 200ms
Type "cover_story repo"
Sleep 200ms
Enter
Sleep 58s
Type "echo Use /pkood:status to see status of all sessions."
Enter
Type "/pkood:sta"
Sleep 500ms
Enter
Sleep 500ms
Enter
Sleep 6s
Escape
Type "OB"
Enter
Sleep 25s
Ctrl+B
Type "d"
Sleep 500ms
Type "echo At any time you can detach from a session by pressing Ctrl+B then D"
Enter
Sleep 1s
Type "echo and connect to other session using command line pkood attach <session_name>"
Enter
Type "pkood ls"
Enter
Sleep 500ms
Type "pkood attach tellem-mypy"
Enter
Escape
Type "[?1;2c"
Escape
Type "[>1;95;0c"
Sleep 19s
Enter
Sleep 11s
Ctrl+B
Sleep 500ms
Type "d"
Sleep 2.5s
Type "echo Now attach back to the monitor session"
Enter
Type "pkood attach monitor"
Enter
Escape
Type "[?1;2c"
Escape
Type "[>1;95;0c"
Sleep 4s
Type "echo skills /pkood:review and /pkood:auto allows you to unblock other sessions"
Enter
Sleep 1s
Type "/pkood:auto"
Sleep 500ms
Enter
Sleep 19.5s
Ctrl+B
Type "d"
Sleep 500ms

