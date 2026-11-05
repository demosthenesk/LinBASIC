OPTION BASE 1
TYPE Pt
  x AS INTEGER
  y AS SINGLE
  nm AS STRING * 4
END TYPE
OPEN "OUT.TXT" FOR OUTPUT AS #1
DIM a(5), b(-2 TO 2, 3) AS LONG, s$(3), p(2) AS Pt
PRINT #1, LBOUND(a); UBOUND(a); LBOUND(b, 1); UBOUND(b, 1); LBOUND(b, 2); UBOUND(b, 2)
FOR i = -2 TO 2: FOR j = 1 TO 3: b(i, j) = i * 100 + j: NEXT: NEXT
PRINT #1, b(-2, 1); b(2, 3); b(0, 2)
s$(1) = "one": s$(2) = "two": s$(3) = s$(1) + s$(2): PRINT #1, s$(3)
p(1).x = 5: p(1).y = 2.5: p(1).nm = "abcdef": p(2) = p(1): p(2).x = 7
PRINT #1, p(1).x; p(1).y; p(1).nm; p(2).x; p(2).nm; LEN(p(1))
REDIM c(10) AS INTEGER: c(10) = 99: PRINT #1, c(10); UBOUND(c)
REDIM c(3): PRINT #1, c(3); UBOUND(c)
ERASE c
q(3) = 4: PRINT #1, q(3); UBOUND(q)
DIM m%(2, 2): m%(1, 2) = 12: m%(2, 1) = 21: PRINT #1, m%(1, 2); m%(2, 1)
CLOSE
