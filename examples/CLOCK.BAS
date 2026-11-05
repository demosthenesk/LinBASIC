' CLOCK.BAS - an analog clock: SCREEN 12, CIRCLE, LINE and ON TIMER
' Make EXE: Linux - DOS window (or Windows - DOS window)
DEFINT A-Z
DECLARE SUB Hand (x0, y0, x1, y1, c)
CONST PI = 3.141593
DIM hx(1 TO 3), hy(1 TO 3)
cx = 320: cy = 248: r = 180
SCREEN 12
CIRCLE (cx, cy), r + 12, 9: PAINT (cx, cy), 1, 9
CIRCLE (cx, cy), r + 12, 15
FOR i = 0 TO 59                             ' the dial
  a! = i * PI / 30
  IF i MOD 5 = 0 THEN l = 20 ELSE l = 6
  LINE (cx + (r - l) * SIN(a!), cy - (r - l) * COS(a!))-(cx + r * SIN(a!), cy - r * COS(a!)), 15
NEXT
FOR k = 1 TO 3: hx(k) = cx: hy(k) = cy: NEXT
COLOR 14: LOCATE 2, 2: PRINT "LinBASIC clock - press any key to end"
ON TIMER(1) GOSUB Tick                       ' redraw the hands every second
TIMER ON
GOSUB Tick
DO: LOOP WHILE INKEY$ = ""
END

Tick:
  t$ = TIME$
  hh = VAL(LEFT$(t$, 2)) MOD 12: mm = VAL(MID$(t$, 4, 2)): ss = VAL(RIGHT$(t$, 2))
  FOR k = 1 TO 2: Hand cx, cy, hx(k), hy(k), 1: NEXT         ' erase the old hands
  LINE (cx, cy)-(hx(3), hy(3)), 1
  a! = (hh + mm / 60!) * PI / 6: hx(1) = cx + r * .5 * SIN(a!): hy(1) = cy - r * .5 * COS(a!)
  a! = (mm + ss / 60!) * PI / 30: hx(2) = cx + r * .75 * SIN(a!): hy(2) = cy - r * .75 * COS(a!)
  a! = ss * PI / 30: hx(3) = cx + r * .88 * SIN(a!): hy(3) = cy - r * .88 * COS(a!)
  Hand cx, cy, hx(1), hy(1), 14
  Hand cx, cy, hx(2), hy(2), 11
  LINE (cx, cy)-(hx(3), hy(3)), 12
  CIRCLE (cx, cy), 5, 15: PAINT (cx, cy), 15, 15
  COLOR 11: LOCATE 30, 37: PRINT t$;
RETURN

SUB Hand (x0, y0, x1, y1, c)                ' a thick hand: three parallel lines
  FOR d = -1 TO 1
    LINE (x0 + d, y0)-(x1 + d, y1), c
    LINE (x0, y0 + d)-(x1, y1 + d), c
  NEXT
END SUB
