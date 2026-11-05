' STARS.BAS - SCREEN 13 starfield (press any key to quit)
DEFINT A-Z
CONST N = 200
DIM x(N) AS SINGLE, y(N) AS SINGLE, z(N) AS SINGLE
SCREEN 13
RANDOMIZE TIMER
FOR i = 1 TO N: x(i) = RND * 640 - 320: y(i) = RND * 400 - 200: z(i) = RND * 255 + 1: NEXT
FOR c = 0 TO 63: PALETTE 16 + c, 65536 * c + 256 * c + c: NEXT
DO
  WAIT &H3DA, 8
  FOR i = 1 TO N
    sx = 160 + x(i) * 64 / z(i): sy = 100 + y(i) * 64 / z(i)
    IF sx >= 0 AND sx < 320 AND sy >= 0 AND sy < 200 THEN PSET (sx, sy), 0
    z(i) = z(i) - 2
    IF z(i) < 1 THEN z(i) = 255: x(i) = RND * 640 - 320: y(i) = RND * 400 - 200
    sx = 160 + x(i) * 64 / z(i): sy = 100 + y(i) * 64 / z(i)
    IF sx >= 0 AND sx < 320 AND sy >= 0 AND sy < 200 THEN PSET (sx, sy), 16 + (255 - z(i)) \ 4
  NEXT
LOOP WHILE INKEY$ = ""
SCREEN 0
