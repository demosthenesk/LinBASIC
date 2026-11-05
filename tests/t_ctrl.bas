OPEN "OUT.TXT" FOR OUTPUT AS #1
FOR i = 1 TO 3: FOR j = 3 TO 1 STEP -1: PRINT #1, i * 10 + j; : NEXT j, i
PRINT #1,
FOR x = 0 TO 1 STEP .25: PRINT #1, x; : NEXT: PRINT #1, x
FOR k = 5 TO 1: PRINT #1, "never": NEXT: PRINT #1, "k="; k
n = 0
DO: n = n + 1: LOOP UNTIL n >= 5: PRINT #1, n
DO WHILE n > 0: n = n - 2: LOOP: PRINT #1, n
DO UNTIL n = 10: n = n + 1: IF n = 7 THEN EXIT DO
LOOP: PRINT #1, n
WHILE n < 12: n = n + 1: WEND: PRINT #1, n
FOR i = 1 TO 10: IF i = 4 THEN EXIT FOR
NEXT: PRINT #1, "i="; i
FOR t = 1 TO 6
  SELECT CASE t
    CASE 1: PRINT #1, "one";
    CASE 2, 3: PRINT #1, "two-three";
    CASE 4 TO 5: PRINT #1, "four-five";
    CASE ELSE: PRINT #1, "else";
  END SELECT
NEXT: PRINT #1,
s$ = "m"
SELECT CASE s$
  CASE "a" TO "l": PRINT #1, "first"
  CASE IS >= "m": PRINT #1, "second"
END SELECT
v = 15
IF v < 10 THEN
  PRINT #1, "lt10"
ELSEIF v < 20 THEN
  PRINT #1, "lt20"
ELSE
  PRINT #1, "big"
END IF
IF v = 15 THEN PRINT #1, "eq"; : PRINT #1, "!" ELSE PRINT #1, "ne"
IF v > 100 THEN PRINT #1, "x" ELSE IF v > 10 THEN PRINT #1, "nested" ELSE PRINT #1, "no"
GOSUB g1: GOSUB g1
FOR q = 1 TO 3: ON q GOSUB a1, a2, a3: NEXT
ON 2 GOTO l1, l2
l1: PRINT #1, "l1"
l2: PRINT #1, "l2"
10 PRINT #1, "line10"
IF q = 4 THEN GOTO 30
20 PRINT #1, "skipped"
30 PRINT #1, "line30"
CLOSE
END
g1: PRINT #1, "gosub": RETURN
a1: PRINT #1, "a1": RETURN
a2: PRINT #1, "a2": RETURN
a3: PRINT #1, "a3": RETURN
