OPEN "OUT.TXT" FOR OUTPUT AS #1
s$ = "Hello, World"
PRINT #1, LEFT$(s$, 5); "|"; RIGHT$(s$, 5); "|"; MID$(s$, 8); "|"; MID$(s$, 3, 4); "|"; MID$(s$, 50); "|"
PRINT #1, INSTR(s$, "o"); INSTR(6, s$, "o"); INSTR(s$, "xyz"); INSTR(s$, ""); INSTR(20, s$, "")
PRINT #1, "["; LTRIM$("  ab  "); "]["; RTRIM$("  ab  "); "]"
PRINT #1, UCASE$("mixed Case 123"); LCASE$("MIXED Case")
PRINT #1, "["; SPACE$(3); "]"; STRING$(5, "*"); STRING$(3, 65); LEN(""); LEN(s$)
PRINT #1, ASC("A"); CHR$(97); ASC(CHR$(200))
MID$(s$, 1, 5) = "HELLO": PRINT #1, s$
MID$(s$, 8) = "WORLDXXXX": PRINT #1, s$
t$ = SPACE$(10): LSET t$ = "abc": PRINT #1, "["; t$; "]"
RSET t$ = "abc": PRINT #1, "["; t$; "]"
PRINT #1, CVI(MKI$(-1234)); CVL(MKL$(123456789)); CVS(MKS$(1.5)); CINT(CVD(MKD$(1024#)))
PRINT #1, LEN(MKI$(1)); LEN(MKD$(1))
PRINT #1, CVSMBF(MKSMBF$(3.25)); CVDMBF(MKDMBF$(-12.5#))
a$ = "abc": b$ = a$: b$ = b$ + "def": PRINT #1, a$; " "; b$
DIM f AS STRING * 6
f = "abcdefgh": PRINT #1, "["; f; "]"; LEN(f)
f = "xy": PRINT #1, "["; f; "]"
x$ = "": FOR i = 1 TO 5: x$ = x$ + CHR$(64 + i): NEXT: PRINT #1, x$
PRINT #1, "abc" + "def" = "abcdef"; "a" <> "b"
CLOSE
