OPEN "OUT.TXT" FOR OUTPUT AS #1
PRINT #1, USING "###.##"; 1.005; 12.345; -1.5; 999.999; 0
PRINT #1, USING "#####"; 12345; 123456; -1234
PRINT #1, USING "+##.#"; 1.25; -1.25
PRINT #1, USING "##.#-"; 1.25; -1.25
PRINT #1, USING "$$###.##"; 12.5; -12.5
PRINT #1, USING "**###.#"; 12.5
PRINT #1, USING "**$##.##"; 3.5
PRINT #1, USING "#,###,###"; 1234567
PRINT #1, USING "##.##^^^^"; 1234.5; .00012
PRINT #1, USING ".###"; .5
PRINT #1, USING "!"; "hello"
PRINT #1, USING "\   \"; "hello world"
PRINT #1, USING "&!"; "ab"; "cd"
PRINT #1, USING "Total: ###.## Units"; 45.678
PRINT #1, USING "_###"; 5
PRINT #1, USING "## "; 1; 2; 3;
PRINT #1, "end"
PRINT #1, USING "#.##"; 9.999
PRINT #1, USING "###"; -12; -123
CLOSE
