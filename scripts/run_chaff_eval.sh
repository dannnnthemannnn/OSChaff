#!/usr/bin/env bash
# run_chaff_eval.sh — run OSWorld-V2 tasks BASELINE vs an OSChaff FORK and print the
# per-task score delta. Pure glue around the stock OSWorld-V2 runner (nothing forked).
#
#   ./run_chaff_eval.sh \
#       --osworld /path/to/OSWorld-V2 \
#       --fork    /path/to/OSChaff/forks/demo \
#       --tasks   "007 016 002" \
#       [--model claude-sonnet-4-6] [--steps 150] [--assets <orig_assets_dir>]
#
# Requires: ANTHROPIC_API_KEY in the environment, a working OSWorld-V2 checkout
# (provider configured), gated tasks+assets already downloaded, hosted mock sites
# live at web.hku.icu (the default).
set -euo pipefail

MODEL="claude-sonnet-4-6"; STEPS=150; NUM_ENVS=1
OSWORLD=""; FORK=""; TASKS=""; ORIG_ASSETS=""
while [[ $# -gt 0 ]]; do case "$1" in
  --osworld) OSWORLD="$2"; shift 2;;
  --fork)    FORK="$2"; shift 2;;
  --tasks)   TASKS="$2"; shift 2;;
  --model)   MODEL="$2"; shift 2;;
  --steps)   STEPS="$2"; shift 2;;
  --assets)  ORIG_ASSETS="$2"; shift 2;;
  *) echo "unknown flag: $1"; exit 1;;
esac; done

[[ -n "$OSWORLD" && -n "$FORK" && -n "$TASKS" ]] || { echo "need --osworld, --fork, --tasks"; exit 1; }
[[ -n "${ANTHROPIC_API_KEY:-}" ]] || { echo "set ANTHROPIC_API_KEY"; exit 1; }
: "${ORIG_ASSETS:=$OSWORLD/cache/osworld_v2_assets}"   # your downloaded gated assets
TASK_CLASS="$OSWORLD/evaluation_examples/task_class"
export WEBSITE_HOST_SUFFIX="${WEBSITE_HOST_SUFFIX:-web.hku.icu}"

# --- subset meta json: {"tasks": ["007","016",...]} ------------------------
META="$(mktemp -t chaff_meta.XXXX.json)"
python3 - "$META" $TASKS <<'PY'
import json, sys
open(sys.argv[1], "w").write(json.dumps({"tasks": [t.zfill(3) for t in sys.argv[2:]]}))
PY

run_set () {  # $1=label  $2=asset_base  $3=result_dir
  echo ">>> running $1 (assets=$2)"
  ( cd "$OSWORLD" && OSWORLD_FILE_BASE_URL="$2" \
    uv run python scripts/python/run_multienv_claude.py \
      --headless --observation_type screenshot --action_space claude_computer_use \
      --model "$MODEL" --max_steps "$STEPS" --num_envs "$NUM_ENVS" \
      --test_all_meta_path "$META" --result_dir "$3" )
}

# --- BASELINE: stock tasks + original assets -------------------------------
run_set baseline "$ORIG_ASSETS" "$OSWORLD/results/chaff_baseline"

# --- FORK: overlay perturbed task_*.py + merged assets ---------------------
BACKUP="$(mktemp -d)"; MERGED="$(mktemp -d)"
echo ">>> overlaying fork (backup of task_class -> $BACKUP)"
for py in "$FORK"/tasks/task_*.py; do
  base="$(basename "$py")"
  [[ -f "$TASK_CLASS/$base" ]] && cp "$TASK_CLASS/$base" "$BACKUP/$base"
  cp "$py" "$TASK_CLASS/$base"
done
rsync -a "$ORIG_ASSETS"/ "$MERGED"/            # originals ...
rsync -a "$FORK"/assets/ "$MERGED"/            # ... perturbed/injected on top
restore () { for b in "$BACKUP"/*; do cp "$b" "$TASK_CLASS/$(basename "$b")"; done; }
trap restore EXIT
run_set fork "$MERGED" "$OSWORLD/results/chaff_fork"
restore; trap - EXIT

# --- scores + delta --------------------------------------------------------
score () { local dir="$1" id="$2"; local f
  f="$(find "$dir" -path "*${id}*/result.txt" 2>/dev/null | head -1)"
  [[ -n "$f" ]] && cat "$f" | tr -d '[:space:]' || echo "NA"; }

printf "\n%-8s %-10s %-10s %-8s\n" task baseline fork delta
printf -- "------------------------------------------\n"
for t in $TASKS; do id="$(printf '%03d' "$((10#$t))")"
  b="$(score "$OSWORLD/results/chaff_baseline" "$id")"
  f="$(score "$OSWORLD/results/chaff_fork" "$id")"
  d="$(python3 -c "b='$b';f='$f'; print(f'{float(f)-float(b):+.2f}' if b not in('NA','') and f not in('NA','') else '?')" 2>/dev/null || echo '?')"
  printf "%-8s %-10s %-10s %-8s\n" "$id" "$b" "$f" "$d"
done
echo
echo "(baseline+fork result dirs under $OSWORLD/results/. Negative delta = chaff made it harder.)"
