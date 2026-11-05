' PHONES.BAS - TYPE records in a RANDOM file, listed with PRINT USING
' Make EXE: Linux - terminal (or Windows - cmd console)
TYPE Person
  nam AS STRING * 18
  phone AS STRING * 16
  age AS INTEGER
END TYPE
DIM p AS Person
OPEN "PHONES.DAT" FOR RANDOM AS #1 LEN = LEN(p)
IF LOF(1) = 0 THEN                          ' first run: create the file
  FOR i = 1 TO 4
    READ p.nam, p.phone, p.age
    PUT #1, i, p
  NEXT
END IF
DATA "Anna Papadopoulou", "+30 210 555 0101", 34
DATA "Nikos Georgiou", "+30 231 555 0102", 51
DATA "Maria Ioannou", "+30 261 555 0103", 27
DATA "Kostas Dimitriou", "+30 281 555 0104", 45
PRINT "Name               Phone             Age"
PRINT STRING$(40, "-")
FOR i = 1 TO LOF(1) \ LEN(p)
  GET #1, i, p
  PRINT USING "\                \ \              \ ###"; p.nam; p.phone; p.age
NEXT
CLOSE #1
PRINT USING "## records, ##### bytes each"; i - 1; LEN(p)
