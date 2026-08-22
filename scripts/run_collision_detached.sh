#!/usr/bin/env bash
# Run the collision test suite detached.
# Usage: ./run_collision_detached.sh "COL-1,COL-2,COL-3" 60 20

set -e
TESTS="$1"
TIMEOUT="${2:-60}"
COOLDOWN="${3:-20}"
LOG=/home/z/my-project/localmind/scratch/collision-detached.log

pkill -f "LOCALMIND_PORT=8765" 2>/dev/null || true
sleep 2

setsid bash -c "
  cd /home/z/my-project/localmind/backend
  python3 /home/z/my-project/scripts/lm_collision_tests.py --tests '$TESTS' --timeout $TIMEOUT --cooldown $COOLDOWN > $LOG 2>&1
" < /dev/null > /dev/null 2>&1 &

BENCH_PID=$!
echo "Started collision benchmark PID=$BENCH_PID, log=$LOG"
sleep 3
echo "--- first 10 lines of log ---"
head -10 "$LOG" 2>/dev/null || echo "(log not yet created)"
