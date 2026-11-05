SCREEN 13
DATA 3,1,30,0, 5,2,50,0, 8,3,80,0, 13,4,120,0, 20,5,170,0, 37,6,260,0
FOR i = 1 TO 6: READ r, c, x, a: CIRCLE (x, 45), r, c: NEXT
CIRCLE (40, 140), 30, 7, , , 1
CIRCLE (110, 140), 30, 8, , , .5
CIRCLE (180, 140), 25, 9, , , 2
CIRCLE (250, 140), 10, 10, , , 1
CIRCLE (290, 140), 6, 11, , , 1
OPEN "OUT.TXT" FOR OUTPUT AS #1
FOR y = 0 TO 199
 r$ = ""
 FOR x = 0 TO 319: r$ = r$ + CHR$(48 + (POINT(x, y) AND 63)): NEXT
 PRINT #1, r$
NEXT
CLOSE
