#!/usr/bin/env bash
# Build the LinBASIC AppImages on Ubuntu 24.04 x86_64:
#   build/LinBASIC-<ver>/LinBASIC-<ver>-x86_64.AppImage   IDE (Linpad++ based) + compiler
#   build/LinBASIC-<ver>/lbc-<ver>-x86_64.AppImage        command line compiler only
# Build deps: sudo apt install build-essential tcc libx11-dev libxext-dev libpulse-dev \
#             python3.12-venv libxcb-cursor0 curl git
# Windows programs are made with the x86_64-win32-tcc cross compiler, built here from tinycc.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${BUILD:-$SRC/build}"
PY=python3.12
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/compiler/lbc/driver.py")"
TOOLS="$BUILD/tools"
mkdir -p "$TOOLS"
fetch() { [ -s "$2" ] || curl -sSL -o "$2" "$1"; }
APPIMAGETOOL="${APPIMAGETOOL:-$TOOLS/appimagetool-x86_64.AppImage}"
RUNTIME="${RUNTIME:-$TOOLS/runtime-x86_64}"
EXCLUDELIST="${EXCLUDELIST:-$TOOLS/excludelist}"
fetch https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage "$APPIMAGETOOL"
fetch https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64 "$RUNTIME"
fetch https://raw.githubusercontent.com/AppImageCommunity/pkg2appimage/master/excludelist "$EXCLUDELIST"
chmod +x "$APPIMAGETOOL"

echo "== LinBASIC $VERSION"
OUT="$BUILD/LinBASIC-$VERSION"          # every release in its own folder
mkdir -p "$OUT"
# ------------------------------------------------------------- runtime library
sh "$SRC/runtime/build.sh" clean
sh "$SRC/runtime/build.sh"
# --------------------------------------- Windows cross compiler + runtime
TINYCC_COMMIT=32d1c0a5614b9979768b3711726db3d601750ed3      # tinycc mob, 2026-11-04
TCCW_SRC="$TOOLS/tinycc"
if [ ! -x "$TCCW_SRC/x86_64-win32-tcc" ]; then
  [ -d "$TCCW_SRC/.git" ] || git clone -q https://github.com/TinyCC/tinycc "$TCCW_SRC"
  ( cd "$TCCW_SRC" && git checkout -q "$TINYCC_COMMIT" && ./configure >/dev/null && \
    make -s x86_64-win32-tcc && make -s x86_64-win32-libtcc1.a )
fi
TCCW="$BUILD/tccwin-full"           # with the Windows headers: used to build the runtime only
rm -rf "$TCCW"; mkdir -p "$TCCW/lib" "$TCCW/include"
cp "$TCCW_SRC/x86_64-win32-tcc" "$TCCW/"
cp -r "$TCCW_SRC/win32/include/"* "$TCCW/include/"
cp "$TCCW_SRC/include/"*.h "$TCCW/include/"
cp "$TCCW_SRC/win32/lib/"*.def "$TCCW/lib/"
cp "$TCCW_SRC/x86_64-win32-libtcc1.a" "$TCCW/lib/"
grep -v '^;' "$SRC/packaging/win/kernel32-extra.def" >> "$TCCW/lib/kernel32.def"
cp "$SRC/packaging/win/winmm.def" "$TCCW/lib/"
TCCWIN="$TCCW" sh "$SRC/runtime/build.sh" win
mkdir -p "$BUILD/icustub"
gcc -shared -fPIC -O2 -Wl,-soname,libicudata.so.73 -o "$BUILD/icustub/libicudata.so.73" "$SRC/packaging/icustub/icudata_stub.c"

EXCL="$(grep -v '^\s*#' "$EXCLUDELIST" | awk '{print $1}' | grep -v '^$' | sed 's/\.so.*//' | sort -u)"
is_excluded() { local b="${1%%.so*}"; grep -qx "$b" <<<"$EXCL"; }

# ---------------------------------------------- common: python + compiler kit
python_into() {   # $1 = AppDir
  local A="$1"
  mkdir -p "$A/usr/bin" "$A/usr/lib"
  cp -L /usr/bin/python3.12 "$A/usr/bin/python3.12"
  cp -a /usr/lib/python3.12 "$A/usr/lib/"
  ( cd "$A/usr/lib/python3.12" && rm -rf test idlelib tkinter turtledemo ensurepip lib2to3 pydoc_data pydoc.py \
      config-3.12-* dist-packages site-packages venv sitecustomize.py && \
    find . -name '__pycache__' -prune -exec rm -rf {} + && find . -type d -name tests -prune -exec rm -rf {} + )
}

kit_into() {      # $1 = LINBASIC_HOME inside the AppDir
  local H="$1"
  mkdir -p "$H/compiler" "$H/runtime/include" "$H/tcc" "$H/examples"
  cp "$SRC/compiler/lbc.py" "$H/compiler/"
  cp -a "$SRC/compiler/lbc" "$H/compiler/"
  find "$H/compiler" -name '__pycache__' -prune -exec rm -rf {} +
  cp "$SRC/runtime/qbrt.h" "$SRC/runtime/libqbrt.a" "$H/runtime/"
  cp "$SRC/runtime/include/"* "$H/runtime/include/"
  # Windows target: the cross compiler, import definitions and the Windows runtime (no headers needed)
  mkdir -p "$H/runtime/win" "$H/tccwin/lib"
  cp "$SRC/runtime/win/libqbrt.a" "$H/runtime/win/"
  cp "$TCCW/x86_64-win32-tcc" "$H/tccwin/"
  cp "$TCCW/lib/"*.def "$TCCW/lib/x86_64-win32-libtcc1.a" "$H/tccwin/lib/"
  cp -L /usr/bin/tcc "$H/tcc/tcc"
  cp /usr/lib/x86_64-linux-gnu/tcc/libtcc1.a "$H/tcc/"
  cp /usr/lib/x86_64-linux-gnu/crt1.o /usr/lib/x86_64-linux-gnu/crti.o /usr/lib/x86_64-linux-gnu/crtn.o \
     /usr/lib/x86_64-linux-gnu/libc_nonshared.a "$H/tcc/"
  cp "$SRC/examples/"*.BAS "$H/examples/"
  cp "$SRC/LICENSE" "$H/LICENSE"
  cp "$SRC/README.md" "$H/README.md"
}

collect() {       # $1 = AppDir, $2 = binary
  local A="$1"
  ldd "$2" 2>/dev/null | awk '/=> \// {print $1" "$3}' | while read -r name path; do
    case "$path" in "$A"/*|/usr/local/*) continue;; esac
    is_excluded "$name" && continue
    case "$name" in libz.so*|libpython*|libQt6*|libicu*) continue;; esac
    case "$name" in libglib-2.0*|libgthread*|libgio-2*|libgobject*|libpcre2*|libdbus-1*|libsystemd*|libcap.so*|\
      libgcrypt*|libgpg-error*|liblz4*|libzstd*|libgssapi*|libkrb5*|libk5crypto*|libkeyutils*|libcom_err*|\
      libgnutls*|libp11-kit*|libidn2*|libunistring*|libtasn1*|libnettle*|libhogweed*|libgmp*|libbsd*|libmd.so*|\
      libXau*|libXdmcp*|libcrypt.so*|libdb-5*|libreadline*|libpanelw*|libncursesw*|libtinfo*|libavahi*|\
      libssl.so*|libcrypto.so*|libsqlite3*) continue;; esac
    case "$name" in libgtk-*|libgdk*|libgmodule*|libmount*|libblkid*|libselinux*|libcairo*|libpixman*|libpango*|\
      libthai*|libdatrie*|libgraphite2*|libepoxy*|libX*|libatk*|libatspi*|libjpeg*|libtiff*|libwebp*|librsvg*) continue;; esac
    [ -e "$A/usr/lib/$name" ] && continue
    cp -L "$path" "$A/usr/lib/$name" && echo "   + $name" && collect "$A" "$path"
  done
}

squash() {        # $1 = AppDir, $2 = output
  rm -f "$2"
  ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" --no-appstream --runtime-file "$RUNTIME" --comp zstd --mksquashfs-opt "-Xcompression-level" --mksquashfs-opt "22" "$1" "$2"
  ( cd "$(dirname "$2")" && sha256sum "$(basename "$2")" > "$(basename "$2").sha256" )
  du -h "$2"
}

# ================================================================ lbc AppImage
A="$BUILD/AppDir-lbc"
rm -rf "$A"
python_into "$A"
H="$A/usr/share/linbasic"
kit_into "$H"
for f in "$A/usr/bin/python3.12" $(find "$A/usr/lib/python3.12/lib-dynload" -name '*.so*' -type f); do collect "$A" "$f"; done
"$A/usr/bin/python3.12" -I -m compileall -q -j0 "$A/usr/lib/python3.12" "$H/compiler" >/dev/null || true
cat > "$A/AppRun" <<'EOF'
#!/bin/sh
# lbc - LinBASIC compiler (AppImage entry point)
HERE="$(dirname "$(readlink -f "$0")")"
export LINBASIC_HOME="$HERE/usr/share/linbasic"
unset PYTHONHOME PYTHONPATH
exec "$HERE/usr/bin/python3.12" -I "$LINBASIC_HOME/compiler/lbc.py" "$@"
EOF
chmod 755 "$A/AppRun"
cat > "$A/lbc.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=lbc
Comment=QB 4.5 compatible BASIC compiler for Linux
Exec=lbc %F
Icon=linbasic
Terminal=true
Categories=Development;
EOF
cp "$SRC/ide/linbasic/res/icons/linbasic.svg" "$A/linbasic.svg"
cp "$SRC/ide/linbasic/res/icons/linbasic-256.png" "$A/.DirIcon"
squash "$A" "$OUT/lbc-$VERSION-x86_64.AppImage"

# ================================================================ IDE AppImage
A="$BUILD/AppDir-ide"
rm -rf "$A"
python_into "$A"
H="$A/usr/share/linbasic"
kit_into "$H"
LIBDIR="$H/lib"
mkdir -p "$LIBDIR" "$A/usr/share/applications" "$A/usr/share/icons/hicolor/scalable/apps" \
         "$A/usr/share/icons/hicolor/256x256/apps" "$A/usr/share/mime/packages"
VENV="$BUILD/venv"
[ -x "$VENV/bin/pip" ] || $PY -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade "PyQt6==6.12.*" "PyQt6-Qt6==6.12.*" "PyQt6-QScintilla==2.14.*" regex 2>/dev/null || \
"$VENV/bin/pip" install -q --upgrade PyQt6 PyQt6-Qt6 PyQt6-QScintilla regex
SP="$("$VENV/bin/python" -c 'import site;print(site.getsitepackages()[0])')"
cp -a "$SP/regex" "$LIBDIR/" && rm -rf "$LIBDIR/regex/tests"
mkdir -p "$LIBDIR/PyQt6"
cp -a "$SP/PyQt6/__init__.py" "$LIBDIR/PyQt6/"
cp -a "$SP"/PyQt6/sip* "$LIBDIR/PyQt6/" 2>/dev/null || true
for m in QtCore QtGui QtWidgets QtNetwork QtPrintSupport QtSvg QtDBus Qsci; do cp -a "$SP/PyQt6/$m".abi3.so "$LIBDIR/PyQt6/"; done
mkdir -p "$LIBDIR/PyQt6/Qt6/lib" "$LIBDIR/PyQt6/Qt6/plugins"
cp -a "$SP/PyQt6/Qt6/qsci" "$LIBDIR/PyQt6/Qt6/" 2>/dev/null || true
QT="$SP/PyQt6/Qt6"
for l in Core Gui Widgets Network PrintSupport DBus Svg XcbQpa WaylandClient WaylandEglClientHwIntegration OpenGL EglFSDeviceIntegration; do
  cp -a "$QT"/lib/libQt6$l.so* "$LIBDIR/PyQt6/Qt6/lib/" 2>/dev/null || true
done
cp -a "$QT"/lib/libicu*.so* "$LIBDIR/PyQt6/Qt6/lib/"
cp -a "$SP"/PyQt6/Qt6/lib/libqscintilla2_qt6.so* "$LIBDIR/PyQt6/Qt6/lib/" 2>/dev/null || true
for p in platforms platformthemes platforminputcontexts imageformats iconengines printsupport xcbglintegrations \
         wayland-decoration-client wayland-graphics-integration-client wayland-shell-integration tls; do
  [ -d "$QT/plugins/$p" ] && cp -a "$QT/plugins/$p" "$LIBDIR/PyQt6/Qt6/plugins/"
done
rm -f "$LIBDIR"/PyQt6/Qt6/plugins/platforms/{libqeglfs,libqlinuxfb,libqvnc,libqvkkhrdisplay}.so "$LIBDIR"/PyQt6/Qt6/plugins/imageformats/libqpdf.so 2>/dev/null || true
[ -d "$QT/translations" ] && { mkdir -p "$LIBDIR/PyQt6/Qt6/translations"; cp -a "$QT"/translations/qtbase_*.qm "$LIBDIR/PyQt6/Qt6/translations/" 2>/dev/null || true; }
check_qt_deps() { for need in $(ldd "$1" 2>/dev/null | awk '/libQt6/ {print $1}'); do [ -e "$LIBDIR/PyQt6/Qt6/lib/$need" ] || return 1; done; return 0; }
find "$LIBDIR/PyQt6/Qt6/plugins" -name '*.so' | while read -r f; do check_qt_deps "$f" || { echo "   drop plugin $(basename "$f")"; rm -f "$f"; }; done
# ---- slim down (keeps the IDE AppImage under 30 MB)
cp "$BUILD/icustub/libicudata.so.73" "$LIBDIR/PyQt6/Qt6/lib/libicudata.so.73"
rm -rf "$LIBDIR/PyQt6/Qt6/qsci" "$LIBDIR"/PyQt6/Qt6/plugins/wayland-* "$LIBDIR"/PyQt6/Qt6/lib/libQt6Wayland* \
       "$LIBDIR"/PyQt6/Qt6/plugins/platforms/libqwayland* "$LIBDIR"/PyQt6/Qt6/lib/libQt6EglFS* "$LIBDIR"/PyQt6/Qt6/lib/libQt6OpenGL* \
       "$LIBDIR/PyQt6/Qt6/plugins/xcbglintegrations" "$LIBDIR/PyQt6/Qt6/plugins/tls"
find "$LIBDIR/PyQt6/Qt6/plugins/imageformats" -name '*.so' ! -name 'libqsvg.so' -delete 2>/dev/null || true
( cd "$LIBDIR/PyQt6/Qt6/translations" 2>/dev/null && ls | grep -v -E 'qtbase_(el|de|fr|es|it)\.qm' | xargs rm -f ) || true
cp -a "$SRC/ide/linbasic" "$LIBDIR/"
( cd "$LIBDIR/linbasic/data/localization" && ls | grep -v -E '^(english|english_customizable|greek)\.xml$' | xargs rm -f )
( cd "$LIBDIR/linbasic/data/autoCompletion" && ls | grep -v -E '^(freebasic|vb|c|cpp|python|batch|html|xml)\.xml$' | xargs rm -f )
( cd "$A/usr/lib/python3.12" && rm -rf unittest asyncio xmlrpc sqlite3 curses wsgiref turtle.py multiprocessing \
    lib-dynload/_sqlite3* lib-dynload/_curses* lib-dynload/_test* lib-dynload/_ctypes_test* lib-dynload/xxlimited* lib-dynload/_tkinter* )
find "$LIBDIR/linbasic" -name '__pycache__' -prune -exec rm -rf {} +
export LD_LIBRARY_PATH="$LIBDIR/PyQt6/Qt6/lib:$A/usr/lib"
for f in "$A/usr/bin/python3.12" $(find "$A/usr/lib/python3.12/lib-dynload" "$LIBDIR" -name '*.so*' -type f -not -path '*/platformthemes/*'); do collect "$A" "$f"; done
unset LD_LIBRARY_PATH
# stdlib as sourceless .pyc, the app and compiler keep their sources
( cd "$A/usr/lib/python3.12" && "$A/usr/bin/python3.12" -I -m compileall -q -b -j1 . >/dev/null; find . -name '*.py' -delete )
"$A/usr/bin/python3.12" -I -m compileall -q -j1 "$LIBDIR/linbasic" "$LIBDIR/regex" "$H/compiler" >/dev/null || true
find "$A/usr" -name '*.so*' -type f -exec strip --strip-unneeded {} \; 2>/dev/null || true
install -m 755 "$SRC/packaging/AppRun" "$A/AppRun"
cp "$SRC/packaging/linbasic.desktop" "$A/linbasic.desktop"
cp "$SRC/packaging/linbasic.desktop" "$A/usr/share/applications/"
cp "$SRC/packaging/linbasic-mime.xml" "$A/usr/share/mime/packages/linbasic.xml"
cp "$SRC/ide/linbasic/res/icons/linbasic.svg" "$A/linbasic.svg"
cp "$SRC/ide/linbasic/res/icons/linbasic.svg" "$A/usr/share/icons/hicolor/scalable/apps/linbasic.svg"
cp "$SRC/ide/linbasic/res/icons/linbasic-256.png" "$A/.DirIcon"
cp "$SRC/ide/linbasic/res/icons/linbasic-256.png" "$A/usr/share/icons/hicolor/256x256/apps/linbasic.png"
squash "$A" "$OUT/LinBASIC-$VERSION-x86_64.AppImage"
