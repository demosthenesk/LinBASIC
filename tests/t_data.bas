OPEN "OUT.TXT" FOR OUTPUT AS #1
FOR i = 1 TO 3: READ a, b$: PRINT #1, a; b$: NEXT
RESTORE second
READ c$, d: PRINT #1, c$; d
RESTORE
READ e: PRINT #1, e
READ f$, g$: PRINT #1, "["; f$; "]["; g$; "]"
CLOSE
END
DATA 1, one, 2, "two, too", 3,three
second:
DATA "x y", -5.5
DATA  spaced out  , ""
