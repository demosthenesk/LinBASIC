#!/bin/bash
# qbref.sh FILE.BAS  -> compiles with real BC.EXE in DOSBox, runs it, prints OUT.TXT
set -e
R="${QBREF_DIR:?set QBREF_DIR to a folder with BC.EXE, LINK.EXE, BCOM45.LIB from QB 4.5}"
B=$(basename "$1" .bas); B=$(basename "$B" .BAS); B=${B^^}
sed 's/\r$//; s/$/\r/' "$1" > "$R/$B.BAS"
rm -f "$R/OUT.TXT" "$R/$B.EXE" "$R/$B.OBJ"
cat > "$R/run.conf" <<EOC
[sdl]
nosound=true
[mixer]
nosound=true
[cpu]
cycles=max
[autoexec]
mount c $R
c:
BC $B.BAS ${BCOPT:-/O /E /X /D}; > BC.LOG
LINK $B.OBJ,$B.EXE,NUL,BCOM45.LIB; > LINK.LOG
$B.EXE
exit
EOC
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout ${TMO:-60} dosbox -conf "$R/run.conf" -exit >/dev/null 2>&1 || true
grep -qE "[1-9][0-9]* Severe" "$R/BC.LOG" && grep -v "^$" "$R/BC.LOG" | sed -n '5,$p' | head -20 >&2
[ -f "$R/OUT.TXT" ] && cat "$R/OUT.TXT" | tr -d '\r'
