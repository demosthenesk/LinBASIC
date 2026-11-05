#!/bin/sh
# build.sh - build the LinBASIC runtime library
#   ./build.sh          runtime/libqbrt.a       for Linux programs (gcc)
#   ./build.sh win      runtime/win/libqbrt.a   for 64-bit Windows programs (TCCWIN = folder with x86_64-win32-tcc)
#   ./build.sh win32    runtime/win32/libqbrt.a for 32-bit Windows programs (TCCWIN32 = folder with i386-win32-tcc)
#   ./build.sh clean
cd "$(dirname "$0")" || exit 1
if [ "$1" = clean ]; then rm -f ./*.o libqbrt.a; rm -rf win win32; exit 0; fi
if [ "$1" = win ]; then
  W=${TCCWIN:?set TCCWIN to the folder with x86_64-win32-tcc and its include/lib}
  mkdir -p win
  for f in core print file screen display sound mem fonts win; do
    "$W/x86_64-win32-tcc" -B"$W" -O2 -Wall -c $f.c -o win/$f.o || exit 1
  done
  rm -f win/libqbrt.a && "$W/x86_64-win32-tcc" -B"$W" -ar rcs win/libqbrt.a win/*.o && rm -f win/*.o && echo "runtime/win/libqbrt.a built"
  exit 0
fi
if [ "$1" = win32 ]; then
  W=${TCCWIN32:?set TCCWIN32 to the folder with i386-win32-tcc and its include/lib}
  mkdir -p win32
  for f in core print file screen display sound mem fonts win; do
    "$W/i386-win32-tcc" -B"$W" -O2 -Wall -c $f.c -o win32/$f.o || exit 1
  done
  rm -f win32/libqbrt.a && "$W/i386-win32-tcc" -B"$W" -ar rcs win32/libqbrt.a win32/*.o && rm -f win32/*.o && echo "runtime/win32/libqbrt.a built"
  exit 0
fi
CC=${CC:-gcc}
CFLAGS="-O2 -g0 -fno-pic -fno-stack-protector -fcf-protection=none -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -fno-asynchronous-unwind-tables -Wall -Wno-unused-result -Wno-misleading-indentation -Wno-format-truncation"
for f in core print file screen display sound mem fonts; do
  $CC $CFLAGS -c $f.c -o $f.o || exit 1
done
rm -f libqbrt.a && ar rcs libqbrt.a core.o print.o file.o screen.o display.o sound.o mem.o fonts.o && rm -f ./*.o && echo "runtime/libqbrt.a built"
