' FRACTAL.BAS - the Mandelbrot set in SCREEN 13 (320x200, 256 colours)
' Make EXE: Linux - DOS window (or Windows - DOS window)
DEFINT A-Z
CONST MAXIT = 63
SCREEN 13
FOR i = 1 TO 63                             ' a palette from dark blue to white
  b = i * 3: IF b > 63 THEN b = 63
  g = (i * i) \ 63: r = (i * i \ 63) * i \ 63
  PALETTE i, 65536& * b + 256& * g + r
NEXT
FOR py = 0 TO 199
  y0! = -1.2 + py * 2.4 / 200
  FOR px = 0 TO 319
    x0! = -2.25 + px * 3.2 / 320
    x! = 0: y! = 0: it = 0
    DO WHILE x! * x! + y! * y! < 4 AND it < MAXIT
      xt! = x! * x! - y! * y! + x0!
      y! = 2 * x! * y! + y0!
      x! = xt!
      it = it + 1
    LOOP
    IF it = MAXIT THEN PSET (px, py), 0 ELSE PSET (px, py), it
  NEXT
NEXT
DO: LOOP WHILE INKEY$ = ""
