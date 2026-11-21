#!/usr/bin/env bash
# Overnight autonomous loop for Aibex View (see docs/overnight.md).
# Each iteration runs a fresh headless Claude Code session that does ONE task from PROGRESS.md and commits it
# on an overnight/ branch. Nothing is pushed or deployed. Review in the morning.
#
# Usage (from the repo root, Mac plugged in):
#   ./scripts/overnight.sh                      # until 07:30 or until all tasks are done/blocked
#   DEADLINE=06:00 MAX_ITER=25 MODEL=opus ./scripts/overnight.sh
#
# Env: DEADLINE (HH:MM, default 07:30) · MAX_ITER (default 40) · MAX_TURNS per iteration (default 150)
#      MODEL (optional, e.g. opus / sonnet) · BRANCH (default overnight/<date>) · STALL_LIMIT (default 3)
set -uo pipefail

# keep the Mac awake for the whole run
if [[ -z "${AIBEX_CAFFEINATED:-}" ]] && command -v caffeinate >/dev/null; then
  export AIBEX_CAFFEINATED=1
  exec caffeinate -dimsu "$0" "$@"
fi

cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
DEADLINE="${DEADLINE:-07:30}"
MAX_ITER="${MAX_ITER:-40}"
MAX_TURNS="${MAX_TURNS:-150}"
STALL_LIMIT="${STALL_LIMIT:-3}"
BRANCH="${BRANCH:-overnight/$(date +%Y-%m-%d)}"
STAMP="$(date +%Y%m%d-%H%M)"
LOGDIR="logs/overnight-$STAMP"

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOGDIR/runner.log"; }

command -v claude >/dev/null || { echo "claude not found in PATH"; exit 1; }
command -v uv >/dev/null || { echo "uv not found in PATH"; exit 1; }
[[ -f PROGRESS.md && -f docs/overnight-prompt.md ]] || { echo "kit not installed (PROGRESS.md / docs/overnight-prompt.md missing)"; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree not clean – commit or stash first:"; git status --short; exit 1
fi

mkdir -p "$LOGDIR" logs/screens

# overnight branch from the current HEAD
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then git switch "$BRANCH"; else git switch -c "$BRANCH"; fi
say "branch $BRANCH, deadline $DEADLINE, max $MAX_ITER iterations, logs in $LOGDIR"

# extra readable directory: the raw/data folders next to AIBEX_DATA_DIR (parsed here, .env is not shown to Claude)
ADD_DIRS=()
DATA_DIR="$(grep -E '^AIBEX_DATA_DIR=' .env 2>/dev/null | head -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//')"
if [[ -n "$DATA_DIR" && -d "$DATA_DIR/.." ]]; then ADD_DIRS=(--add-dir "$(cd "$DATA_DIR/.." && pwd)"); fi

ALLOWED=(
  "Read" "Edit" "Write" "Glob" "Grep" "TodoWrite" "TaskCreate" "TaskUpdate" "TaskList" "mcp__playwright"
  "Bash(uv *)" "Bash(npm *)" "Bash(npx *)" "Bash(node *)"
  "Bash(make test*)" "Bash(make accept*)" "Bash(make e2e*)" "Bash(make eval-llm*)" "Bash(make help*)"
  "Bash(git status*)" "Bash(git diff*)" "Bash(git log*)" "Bash(git show *)" "Bash(git ls-files*)"
  "Bash(git add *)" "Bash(git commit *)" "Bash(git rm *)" "Bash(git mv *)"
  "Bash(git branch --show-current)" "Bash(git restore *)" "Bash(git stash *)"
  "Bash(cd *)" "Bash(ls *)" "Bash(cat *)" "Bash(head *)" "Bash(tail *)" "Bash(wc *)" "Bash(grep *)" "Bash(find *)"
  "Bash(sort *)" "Bash(diff *)" "Bash(echo *)" "Bash(which *)" "Bash(date*)" "Bash(pwd)"
  "Bash(mkdir *)" "Bash(mv *)" "Bash(cp *)" "Bash(touch *)" "Bash(rmdir *)" "Bash(sleep *)"
  "Bash(curl -s http://localhost*)" "Bash(lsof -i*)" "Bash(pkill -f uvicorn*)" "Bash(pkill -f vite*)"
)
# Deny rules win over allow rules, including the interactive allow-list in .claude/settings.json
# (which also applies to headless runs: git switch/checkout, kubectl get, make dev, ...).
DISALLOWED=(
  "Bash(git switch*)" "Bash(git checkout*)" "Bash(git push*)" "Bash(git merge*)" "Bash(git rebase*)"
  "Bash(git reset --hard*)" "Bash(git remote*)" "Bash(git branch -D*)" "Bash(git stash drop*)" "Bash(git stash clear*)"
  "Bash(kubectl*)" "Bash(make deploy*)" "Bash(make restart*)" "Bash(make upload-data*)" "Bash(make k8s-secret*)"
  "Bash(make logs*)" "Bash(make dev*)" "Bash(rm -rf*)"
  "Read(./.env)" "Read(./.env.local)" "Read(./.env.llm)"
  "Bash(cat .env*)" "Bash(head .env*)" "Bash(tail .env*)" "Bash(grep * .env*)" "Bash(cp .env*)"
)
MODEL_ARGS=(); [[ -n "${MODEL:-}" ]] && MODEL_ARGS=(--model "$MODEL")
PROMPT="$(cat docs/overnight-prompt.md)"

past_deadline() {  # true between DEADLINE and noon
  local now; now="$(date +%H:%M)"
  [[ "$now" > "$DEADLINE" && "$now" < "12:00" ]]
}

stalls=0
for ((i = 1; i <= MAX_ITER; i++)); do
  if past_deadline; then say "deadline reached"; break; fi
  # open = todo or partly done, not marked for Vojta
  if ! grep -E '^- \[( |~)\] T[1-9]' PROGRESS.md | grep -vq -- '– Vojta'; then say "no open tasks left"; break; fi

  before="$(git rev-parse HEAD)"
  ilog="$LOGDIR/iter-$(printf %02d "$i").jsonl"
  say "iteration $i start (HEAD ${before:0:7})"
  claude -p "$PROMPT" \
    --permission-mode dontAsk \
    --allowedTools "${ALLOWED[@]}" \
    --disallowedTools "${DISALLOWED[@]}" \
    ${ADD_DIRS[@]+"${ADD_DIRS[@]}"} ${MODEL_ARGS[@]+"${MODEL_ARGS[@]}"} \
    --max-turns "$MAX_TURNS" \
    --output-format stream-json --verbose >"$ilog" 2>&1
  rc=$?
  after="$(git rev-parse HEAD)"
  # clean up stray dev servers
  pkill -f "uvicorn aibex.main" 2>/dev/null; pkill -f "$REPO/frontend/node_modules" 2>/dev/null

  summary="$(tail -c 2000 "$ilog" | tr '\n' ' ' | grep -oE '"result":"[^"]{0,400}' | tail -1 | cut -c11-)"
  say "iteration $i end rc=$rc HEAD ${after:0:7} :: ${summary:-<no summary>}"

  if grep -q "ALL_TASKS_DONE_OR_BLOCKED" "$ilog"; then say "agent reports all tasks done or blocked"; break; fi

  # look only at the final result/error lines – tool output (genomic positions, ids) can contain "429"
  if tail -n 3 "$ilog" | grep -qiE 'usage limit|rate[ _]limit|limit reached|overloaded|"status":? ?429' && [[ "$before" == "$after" ]]; then
    say "usage/rate limit – sleeping 20 min"; sleep 1200; continue
  fi

  if [[ "$before" == "$after" ]]; then
    stalls=$((stalls + 1)); say "no commit this iteration (stall $stalls/$STALL_LIMIT)"
    if ((stalls >= STALL_LIMIT)); then say "stopping: $STALL_LIMIT iterations without progress"; break; fi
    sleep 60
  else
    stalls=0
  fi

  # never leave uncommitted junk between iterations
  if [[ -n "$(git status --porcelain)" ]]; then
    git stash push -u -m "overnight leftover after iteration $i" >/dev/null && say "stashed leftovers of iteration $i"
  fi
done

say "done. Commits on $BRANCH since start:"
git log --oneline "main..$BRANCH" | tee -a "$LOGDIR/runner.log"
say "morning: read PROGRESS.md (Log), $LOGDIR/runner.log, logs/screens/; then make dev and test."
