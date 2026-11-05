DECLARE SUB Inc (x%)
DECLARE SUB Swp (a$, b$)
DECLARE FUNCTION Fib& (n%)
DECLARE FUNCTION Rev$ (s$)
DECLARE SUB Fill (arr%())
DECLARE FUNCTION Counter% ()
DECLARE SUB ShowShared ()
DIM SHARED total AS INTEGER
COMMON SHARED gname$
OPEN "OUT.TXT" FOR OUTPUT AS #1
a% = 5: Inc a%: PRINT #1, a%
Inc (a%): PRINT #1, a%
CALL Inc(a%): PRINT #1, a%
p$ = "first": q$ = "second": Swp p$, q$: PRINT #1, p$; " "; q$
PRINT #1, Fib&(20); Rev$("abcdef")
DIM z%(1 TO 5): Fill z%(): FOR i = 1 TO 5: PRINT #1, z%(i); : NEXT: PRINT #1,
PRINT #1, Counter%; Counter%; Counter%
total = 42: gname$ = "shared": ShowShared
DEF FNsq (x) = x * x
DEF FNmax (a, b)
  IF a > b THEN FNmax = a ELSE FNmax = b
END DEF
PRINT #1, FNsq(7); FNmax(3, 9); FNmax(10, 2)
CLOSE
END

SUB Fill (arr%())
  FOR i = LBOUND(arr%) TO UBOUND(arr%): arr%(i) = i * i: NEXT
END SUB

FUNCTION Counter%
  STATIC c
  c = c + 1
  Counter% = c
END FUNCTION

FUNCTION Fib& (n%)
  IF n% < 2 THEN Fib& = n%: EXIT FUNCTION
  Fib& = Fib&(n% - 1) + Fib&(n% - 2)
END FUNCTION

SUB Inc (x%)
  x% = x% + 1
END SUB

FUNCTION Rev$ (s$)
  r$ = ""
  FOR i = LEN(s$) TO 1 STEP -1: r$ = r$ + MID$(s$, i, 1): NEXT
  Rev$ = r$
END FUNCTION

SUB ShowShared
  PRINT #1, total; gname$
END SUB

SUB Swp (a$, b$)
  SWAP a$, b$
END SUB
