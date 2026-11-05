#!/bin/bash
# build-windows.sh - the portable Windows editions of LinBASIC (Windows 7 SP1 or later)
#   build/LinBASIC-<version>/LinBASIC-<version>-win32.zip   32-bit Windows; makes 32-bit programs
#   build/LinBASIC-<version>/LinBASIC-<version>-win64.zip   64-bit Windows; makes 64-bit programs
# Each zip holds one folder with LinBASIC.exe (the IDE) and lbc.exe (the compiler).
#
# Qt 6 needs Windows 10, so the Windows IDE runs on PyQt5 / Qt 5.15 with Python 3.8 (the last
# versions that support Windows 7); packaging/win/pyqt6shim lets the PyQt6 code run on PyQt5.
#
# Needs (Ubuntu 24.04): gcc-mingw-w64-i686 gcc-mingw-w64-x86-64 binutils-mingw-w64 librsvg2-bin
#                       zip python3-pip, and the tinycc tree that build-appimages.sh fetches.
# Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later.
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$SRC/build"
TOOLS="$BUILD/tools"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/compiler/lbc/driver.py")"
OUT="$BUILD/LinBASIC-$VERSION"
DL="$TOOLS/win-downloads"
PYVER=3.8.20                    # Python 3.8 builds that run on Windows 7 (github.com/adang1345/PythonVista)
TCC_SRC="$TOOLS/tinycc"
mkdir -p "$OUT" "$DL"
echo "== LinBASIC $VERSION for Windows"

# ------------------------------------------------------------------ downloads
for arch in win32 amd64; do
  f="$DL/python-$PYVER-embed-$arch.zip"
  [ -s "$f" ] || curl -sSfL -o "$f" "https://github.com/adang1345/PythonVista/releases/download/v$PYVER/python-$PYVER-embed-$arch.zip"
done
for plat in win32 win_amd64; do
  ls "$DL/wheels-$plat"/PyQt5-*.whl >/dev/null 2>&1 || \
    pip download -q --only-binary=:all: --platform $plat --python-version 3.8 --implementation cp \
      --abi cp38 --abi abi3 --abi none -d "$DL/wheels-$plat" \
      "PyQt5==5.15.11" "PyQt5-Qt5==5.15.2" "PyQt5-sip==12.15.0" "QScintilla==2.14.1" "regex==2024.11.6"
done

# ------------------------------------------- C compilers: cross (Linux) and native (Windows)
[ -x "$TCC_SRC/x86_64-win32-tcc" ] || { echo "run packaging/build-appimages.sh first (tinycc)"; exit 1; }
( cd "$TCC_SRC" && make -s i386-win32-tcc i386-win32-libtcc1.a x86_64-win32-libtcc1.a )
for bits in 32 64; do
  H="$TOOLS/tcc-winhost$bits"
  if [ ! -f "$H/tcc.exe" ]; then
    rm -rf "$H"; cp -a "$TCC_SRC" "$H"
    ( cd "$H" && make -s distclean >/dev/null 2>&1 || true
      if [ $bits = 64 ]; then P=x86_64-w64-mingw32- C=x86_64; else P=i686-w64-mingw32- C=i386; fi
      ./configure --cross-prefix=$P --targetos=WIN32 --cpu=$C >/dev/null
      cp "$TCC_SRC/tccdefs_.h" . && touch tccdefs_.h      # made on the Linux side (c2str.exe cannot run here)
      make -s tcc.exe )
  fi
done
# full kits with the Windows headers: only for building the runtime libraries
for bits in 32 64; do
  if [ $bits = 64 ]; then CC=x86_64-win32-tcc; K="$BUILD/tccwin-full"; else CC=i386-win32-tcc; K="$BUILD/tccwin32-full"; fi
  rm -rf "$K"; mkdir -p "$K/lib" "$K/include"
  cp "$TCC_SRC/$CC" "$K/"
  cp -r "$TCC_SRC/win32/include/"* "$K/include/"; cp "$TCC_SRC/include/"*.h "$K/include/"
  cp "$TCC_SRC/win32/lib/"*.def "$K/lib/"; cp "$TCC_SRC/${CC%-tcc}-libtcc1.a" "$K/lib/"
  grep -v '^;' "$SRC/packaging/win/kernel32-extra.def" >> "$K/lib/kernel32.def"
  cp "$SRC/packaging/win/winmm.def" "$K/lib/"
done
TCCWIN="$BUILD/tccwin-full" sh "$SRC/runtime/build.sh" win
TCCWIN32="$BUILD/tccwin32-full" sh "$SRC/runtime/build.sh" win32

# ------------------------------------------------------------------ launchers
LW="$BUILD/win-launchers"; rm -rf "$LW"; mkdir -p "$LW"
IFS=. read -r V1 V2 V3 <<<"$VERSION"
for bits in 32 64; do
  if [ $bits = 64 ]; then P=x86_64-w64-mingw32-; else P=i686-w64-mingw32-; fi
  for kind in gui cli; do
    if [ $kind = gui ]; then NAME=LinBASIC.exe DESC="LinBASIC IDE"; FL="-DGUI -mwindows -municode";
    else NAME=lbc.exe DESC="LinBASIC compiler"; FL="-municode -mconsole"; fi
    ${P}windres -I "$SRC/packaging/win" -DVER_MAJOR=$V1 -DVER_MINOR=$V2 -DVER_PATCH=$V3 \
      -DVER_STR="\\\"$VERSION\\\"" -DNAME="\\\"$NAME\\\"" -DDESC="\\\"$DESC\\\"" \
      "$SRC/packaging/win/launcher.rc" -O coff -o "$LW/res-$kind-$bits.o"
    ${P}gcc -O2 -s -static -static-libgcc $FL -o "$LW/$bits-$NAME" "$SRC/packaging/win/launcher.c" "$LW/res-$kind-$bits.o"
  done
done

# ------------------------------------------------------------------ assemble
for bits in 32 64; do
  if [ $bits = 64 ]; then arch=amd64 plat=win_amd64 TC=x86_64-win32 RT=win; else arch=win32 plat=win32 TC=i386-win32 RT=win32; fi
  NAME="LinBASIC-$VERSION-win$bits"
  D="$BUILD/win$bits/$NAME"
  rm -rf "$BUILD/win$bits"; mkdir -p "$D"
  # Python
  mkdir -p "$D/python"; ( cd "$D/python" && unzip -q "$DL/python-$PYVER-embed-$arch.zip" )
  rm -f "$D/python/"{_msi,_sqlite3,winsound,_bz2,_ssl}.pyd "$D/python/sqlite3.dll" "$D/python/"libssl-*.dll
  printf 'python38.zip\r\n.\r\n..\\lib\r\n' > "$D/python/python38._pth"
  # PyQt5 + QScintilla + regex
  mkdir -p "$D/lib"
  for w in "$DL/wheels-$plat"/*.whl; do ( cd "$D/lib" && unzip -q -o "$w" ); done
  ( cd "$D/lib" && rm -rf ./*.dist-info PyQt5/bindings PyQt5/uic PyQt5/Qt5/qsci PyQt5/Qt5/qml PyQt5/Qt5/translations \
      PyQt5/Qt5/resources PyQt5/pylupdate* PyQt5/pyrcc* PyQt5/*.pyi PyQt5/py.typed regex/tests )
  ( cd "$D/lib/PyQt5" && for f in *.pyd; do case "$f" in QtCore.pyd|QtGui.pyd|QtWidgets.pyd|QtNetwork.pyd|\
      QtPrintSupport.pyd|QtSvg.pyd|Qsci.pyd|sip.*) ;; *) rm -f "$f";; esac; done )
  ( cd "$D/lib/PyQt5/Qt5/bin" && for f in *; do case "$f" in Qt5Core.dll|Qt5Gui.dll|Qt5Widgets.dll|Qt5Network.dll|\
      Qt5PrintSupport.dll|Qt5Svg.dll|msvcp140.dll|msvcp140_1.dll|vcruntime140*.dll) ;; *) rm -f "$f";; esac; done )
  ( cd "$D/lib/PyQt5/Qt5/plugins" && for p in *; do case "$p" in platforms|styles|imageformats|iconengines|printsupport) ;; \
      *) rm -rf "$p";; esac; done; rm -f platforms/qwebgl.dll platforms/qminimal.dll \
      imageformats/{qicns,qtga,qtiff,qwbmp,qwebp,qgif}.dll )
  cp -a "$SRC/packaging/win/pyqt6shim/PyQt6" "$D/lib/"
  cp -a "$SRC/ide/linbasic" "$D/lib/"
  ( cd "$D/lib/linbasic/data/localization" && ls | grep -v -E '^(english|english_customizable|greek)\.xml$' | xargs rm -f )
  find "$D/lib" -name '__pycache__' -prune -exec rm -rf {} +
  # compiler, runtime and the native C compiler
  mkdir -p "$D/compiler" "$D/runtime/include" "$D/runtime/$RT" "$D/tcc/lib" "$D/examples" "$D/settings"
  cp "$SRC/compiler/lbc.py" "$D/compiler/"; cp -a "$SRC/compiler/lbc" "$D/compiler/"
  find "$D/compiler" -name '__pycache__' -prune -exec rm -rf {} +
  cp "$SRC/runtime/qbrt.h" "$D/runtime/"; cp "$SRC/runtime/include/"* "$D/runtime/include/"
  cp "$SRC/runtime/$RT/libqbrt.a" "$D/runtime/$RT/"
  cp "$TOOLS/tcc-winhost$bits/tcc.exe" "$TOOLS/tcc-winhost$bits/libtcc.dll" "$D/tcc/"
  cp "$TCC_SRC/win32/lib/"*.def "$D/tcc/lib/"
  grep -v '^;' "$SRC/packaging/win/kernel32-extra.def" >> "$D/tcc/lib/kernel32.def"
  cp "$SRC/packaging/win/winmm.def" "$D/tcc/lib/"
  cp "$TCC_SRC/$TC-libtcc1.a" "$D/tcc/lib/libtcc1.a"
  # launchers, examples, documents (text files with CR+LF)
  cp "$LW/$bits-LinBASIC.exe" "$D/LinBASIC.exe"; cp "$LW/$bits-lbc.exe" "$D/lbc.exe"
  for f in "$SRC/examples/"*.BAS; do sed 's/\r*$/\r/' "$f" > "$D/examples/$(basename "$f")"; done
  sed 's/\r*$/\r/' "$SRC/LICENSE" > "$D/LICENSE.txt"
  sed -e "s/@VERSION@/$VERSION/g" -e "s/@BITS@/$bits/g" "$SRC/packaging/win/README-windows.txt" | sed 's/\r*$/\r/' > "$D/README.txt"
  printf 'LinBASIC keeps its settings in this folder (portable mode).\r\nDelete the folder to keep them in %%APPDATA%%\\LinBASIC instead.\r\n' > "$D/settings/README.txt"
  rm -f "$OUT/$NAME.zip"
  ( cd "$BUILD/win$bits" && zip -q -r -9 "$OUT/$NAME.zip" "$NAME" )
  ( cd "$OUT" && sha256sum "$NAME.zip" > "$NAME.zip.sha256" )
  echo "   $OUT/$NAME.zip  ($(du -h "$OUT/$NAME.zip" | cut -f1))"
done
