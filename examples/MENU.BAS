' MENU.BAS - a text-mode menu: box characters, colours, LOCATE and arrow keys
' Make EXE: Linux - DOS window, Linux - terminal or Windows - cmd console
DEFINT A-Z
DIM item$(1 TO 5)
FOR i = 1 TO 5: READ item$(i): NEXT
DATA "New game", "Load game", "Options", "High scores", "Quit"
CONST TOP = 7, LFT = 28, W = 26, H = 10

COLOR 7, 1: CLS
COLOR 0, 7: LOCATE 1, 1: PRINT SPACE$(80);
LOCATE 1, 3: PRINT "LinBASIC demo";
COLOR 0, 0                                   ' shadow
FOR r = 1 TO H: LOCATE TOP + r, LFT + 2: PRINT SPACE$(W); : NEXT
COLOR 15, 3                                  ' window with a double frame
LOCATE TOP, LFT: PRINT CHR$(201); STRING$(W - 2, 205); CHR$(187);
FOR r = 1 TO H - 2: LOCATE TOP + r, LFT: PRINT CHR$(186); SPACE$(W - 2); CHR$(186); : NEXT
LOCATE TOP + H - 1, LFT: PRINT CHR$(200); STRING$(W - 2, 205); CHR$(188);
LOCATE TOP, LFT + 8: PRINT " Main menu ";
COLOR 14, 1: LOCATE 24, 3
PRINT CHR$(24); CHR$(25); " choose   Enter select   Esc quit";

sel = 1
DO
  FOR i = 1 TO 5
    IF i = sel THEN COLOR 15, 4 ELSE COLOR 0, 3
    LOCATE TOP + 1 + i, LFT + 3: PRINT LEFT$("  " + item$(i) + SPACE$(W), W - 6);
  NEXT
  DO: k$ = INKEY$: LOOP WHILE k$ = ""
  SELECT CASE k$
    CASE CHR$(0) + "H": sel = sel - 1: IF sel < 1 THEN sel = 5
    CASE CHR$(0) + "P": sel = sel + 1: IF sel > 5 THEN sel = 1
    CASE CHR$(13)
      IF sel = 5 THEN EXIT DO
      COLOR 15, 1: LOCATE 20, 3: PRINT "You chose: "; item$(sel); SPACE$(20);
    CASE CHR$(27): EXIT DO
  END SELECT
LOOP
COLOR 7, 0: CLS
