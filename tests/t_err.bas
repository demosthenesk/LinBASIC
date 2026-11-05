OPEN "OUT.TXT" FOR OUTPUT AS #1
ON ERROR GOTO handler
z% = 0: x = 1 \ z%
PRINT #1, "after div"
OPEN "NOFILE.XYZ" FOR INPUT AS #2
PRINT #1, "after open"
ERROR 57
PRINT #1, "after error 57"
a$ = MID$("abc", 0)
PRINT #1, "after mid"
count = 0
100 y = LOG(-1)
PRINT #1, "count"; count
ON ERROR GOTO 0
PRINT #1, "done"
CLOSE
END
handler:
PRINT #1, "Error"; ERR; "at"; ERL
count = count + 1
IF ERR = 5 AND count = 1 THEN RESUME NEXT
RESUME NEXT
