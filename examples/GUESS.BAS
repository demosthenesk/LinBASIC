' GUESS.BAS - a number guessing game for the terminal
' Make EXE: Linux - terminal (or Windows - cmd console)
RANDOMIZE TIMER
secret = INT(RND * 100) + 1
PRINT "I am thinking of a number between 1 and 100."
DO
  INPUT "Your guess"; g
  tries = tries + 1
  IF g < secret THEN PRINT "Higher!"
  IF g > secret THEN PRINT "Lower!"
LOOP UNTIL g = secret
COLOR 10: PRINT "Correct!"; : COLOR 7
PRINT " You needed"; tries; "tries."
