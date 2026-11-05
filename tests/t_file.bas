TYPE Rec
  id AS INTEGER
  nm AS STRING * 10
  v AS DOUBLE
END TYPE
DIM r AS Rec
OPEN "OUT.TXT" FOR OUTPUT AS #1
OPEN "T1.DAT" FOR OUTPUT AS #2
PRINT #2, "line one"
PRINT #2, 12; 34; "x"
WRITE #2, "a,b", 5, 6.5
CLOSE #2
OPEN "T1.DAT" FOR APPEND AS #2: PRINT #2, "appended": CLOSE #2
OPEN "T1.DAT" FOR INPUT AS #2
LINE INPUT #2, l$: PRINT #1, "["; l$; "]"
INPUT #2, n1, n2, w$: PRINT #1, n1; n2; w$
INPUT #2, q$, k, z!: PRINT #1, q$; k; z!
LINE INPUT #2, l$: PRINT #1, l$; EOF(2)
CLOSE #2
OPEN "T2.DAT" FOR RANDOM AS #3 LEN = LEN(r)
FOR i = 1 TO 3: r.id = i: r.nm = "name" + STR$(i): r.v = i * 1.5: PUT #3, i, r: NEXT
GET #3, 2, r: PRINT #1, r.id; r.nm; r.v; LOF(3); LOC(3)
CLOSE #3
OPEN "T3.DAT" FOR RANDOM AS #4 LEN = 20
FIELD #4, 8 AS a$, 12 AS b$
LSET a$ = "abc": RSET b$ = "xyz": PUT #4, 1
LSET a$ = "": LSET b$ = "": GET #4, 1: PRINT #1, "["; a$; "]["; b$; "]"
CLOSE #4
OPEN "T4.DAT" FOR BINARY AS #5
x% = 12345: y& = -7: PUT #5, , x%: PUT #5, , y&: s$ = "hi!": PUT #5, , s$
PRINT #1, LOF(5); SEEK(5)
SEEK #5, 1: GET #5, , x2%: GET #5, , y2&: t$ = SPACE$(3): GET #5, , t$
PRINT #1, x2%; y2&; t$; LOC(5)
CLOSE #5
n = FREEFILE: PRINT #1, "free"; n
KILL "T1.DAT": KILL "T2.DAT": KILL "T3.DAT"
NAME "T4.DAT" AS "T5.DAT": KILL "T5.DAT"
CLOSE
