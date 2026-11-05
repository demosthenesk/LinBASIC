OPEN "OUT.TXT" FOR OUTPUT AS #1
a% = 300: b% = 7
PRINT #1, a% \ b%; a% MOD b%; -a% \ b%; -a% MOD b%; a% / b%; a% * b%
c& = 100000: PRINT #1, c& * 3; c& \ 7; c& MOD 7; c& / 8
PRINT #1, 7.6 \ 2; 7.4 MOD 2.5; 2 ^ 0.5; (-8) ^ (1 / 3) = 0
PRINT #1, SQR(2); SIN(1); COS(1); TAN(1); ATN(1); EXP(1); LOG(10)
PRINT #1, SQR(2#); SIN(1#); ATN(1#) * 4
PRINT #1, ABS(-5); ABS(-5.5); SGN(-3); SGN(0); SGN(2.5)
PRINT #1, 5 AND 12; 5 OR 12; 5 XOR 12; NOT 5; 5 EQV 12; 5 IMP 12
PRINT #1, -1 AND 32767; &HFFFF; &HFFFF&; &H7FFF + 1
PRINT #1, 1 < 2; 1 > 2; "abc" = "abc"; "abc" < "abd"; "B" > "a"
RANDOMIZE 7
PRINT #1, RND; RND; RND(0); RND(-2); RND
x! = 1 / 3: y# = x!: PRINT #1, y#; CDBL(x!); CSNG(1# / 3)
PRINT #1, 3 + 4 * 2 ^ 2 - 6 / 3; 2 ^ 3 ^ 2; -2 ^ 2; 10 - 3 - 2
PRINT #1, 1E+38 * 1; 255 \ 16 * 16
i% = 32767: PRINT #1, i% - 1 + 1
CLOSE
