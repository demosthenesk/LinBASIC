#!/bin/bash
# run_tests.sh [names...] : compare LinBASIC output with real QB 4.5 (BC.EXE in DOSBox)
cd "$(dirname "$0")"
mkdir -p expected work
pass=0; fail=0
tests=${@:-$(ls t_*.bas | sed 's/\.bas$//')}
for t in $tests; do
  t=${t%.bas}
  if [ ! -f expected/$t.txt ]; then ./qbref.sh $t.bas > expected/$t.txt 2>expected/$t.bc; fi
  rm -rf work/$t; mkdir -p work/$t
  if ! python3 ../compiler/lbc.py -o work/$t/prog $t.bas 2> work/$t/compile.txt; then
    echo "FAIL $t (compile)"; head -3 work/$t/compile.txt; fail=$((fail+1)); continue
  fi
  (cd work/$t && QB_DISPLAY=headless QB_NOSOUND=1 timeout 20 ./prog > stdout.txt 2> stderr.txt)
  tr -d '\r' < work/$t/OUT.TXT > work/$t/out.txt 2>/dev/null
  if diff -q expected/$t.txt work/$t/out.txt >/dev/null; then pass=$((pass+1)); echo "ok   $t"
  else fail=$((fail+1)); echo "FAIL $t"; diff expected/$t.txt work/$t/out.txt | head -${DIFFN:-12}; fi
done
echo "passed $pass, failed $fail"
