#!/usr/bin/env bash
# Run the LM benchmark in a fully-detached session.
# Usage: ./run_benchmark_detached.sh "CAT2-1,CAT2-2,CAT2-3" 60 15
# Output: /home/z/my-project/localmind/scratch/bench-detached.log
# Results: /home/z/my-project/localmind/scratch/benchmark-results-bench-detached.json

set -e
TESTS="$1"
TIMEOUT="${2:-60}"
COOLDOWN="${3:-15}"
LOG=/home/z/my-project/localmind/scratch/bench-detached.log
RESULTS=/home/z/my-project/localmind/scratch/benchmark-results-bench-detached.json

# Kill any prior server
pkill -f "LOCALMIND_PORT=8765" 2>/dev/null || true
sleep 2

# Detach completely — setsid + nohup + & + disown
setsid bash -c "
  cd /home/z/my-project/localmind/backend
  python3 /home/z/my-project/scripts/lm_benchmark.py --tests '$TESTS' --timeout $TIMEOUT --cooldown $COOLDOWN > $LOG 2>&1
" < /dev/null > /dev/null 2>&1 &

# Print the PID so we can check it later
BENCH_PID=$!
echo "Started benchmark PID=$BENCH_PID, log=$LOG"
sleep 3
echo "--- first 10 lines of log ---"
head -10 "$LOG" 2>/dev/null || echo "(log not yet created)"
