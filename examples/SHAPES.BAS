' SHAPES.BAS - SCREEN 12 graphics: LINE, CIRCLE, PAINT and DRAW
' Make EXE: Linux - DOS window (or Windows - DOS window)
SCREEN 12
LINE (0, 0)-(639, 479), 9, B
COLOR 15: LOCATE 2, 31: PRINT "LinBASIC graphics"
FOR i = 0 TO 7                              ' a row of coloured boxes
  LINE (32 + i * 72, 50)-(92 + i * 72, 110), i + 8, BF
  LINE (32 + i * 72, 50)-(92 + i * 72, 110), 15, B
NEXT
FOR r = 10 TO 100 STEP 10                   ' rings
  CIRCLE (160, 270), r, r \ 10 + 1
NEXT
CIRCLE (420, 270), 150, 14, , , .5          ' an ellipse, filled with PAINT
PAINT (420, 270), 4, 14
CIRCLE (420, 270), 60, 15, 0, 3.14159       ' a half circle
DRAW "C11 BM540,330 M+40,110 M-100,-70 M+120,0 M-100,70 M+40,-110"   ' a star
LINE (30, 445)-(610, 445), 10, , &HF0F0     ' a dashed line
COLOR 7: LOCATE 29, 30: PRINT "Press any key to end";
DO: LOOP WHILE INKEY$ = ""
