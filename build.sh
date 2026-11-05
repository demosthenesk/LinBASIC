#!/bin/sh
# LinBASIC from the source tree:
#   ./build.sh            build runtime/libqbrt.a (needs gcc, libx11-dev, libxext-dev, libpulse-dev)
#   ./build.sh test       run the comparison tests (needs QBREF_DIR with BC.EXE + DOSBox)
#   ./build.sh appimages  build both AppImages (Ubuntu 24.04)
# Then: ./compiler/lbc.py -o hello examples/HELLO.BAS
#       cd ide && LINBASIC_HOME=.. python3 -m linbasic      (needs PyQt6, PyQt6-QScintilla, regex)
cd "$(dirname "$0")" || exit 1
case "$1" in
  test) sh runtime/build.sh && cd tests && ./run_tests.sh ;;
  appimages) sh runtime/build.sh && packaging/build-appimages.sh ;;
  clean) sh runtime/build.sh clean ;;
  *) sh runtime/build.sh ;;
esac
