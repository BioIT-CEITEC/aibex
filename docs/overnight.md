# Overnight autonomous runs – rules for the agent

`scripts/overnight.sh` starts Claude Code headless (`claude -p`) in a loop. Each iteration is a **fresh session**
that does exactly **one task** from `PROGRESS.md` and then stops. Nobody is watching: work carefully, leave a clear trail.

## Each iteration
1. Read `CLAUDE.md`, `docs/acceptance.md`, `docs/api.md`, then `PROGRESS.md` (tasks + Log).
2. Pick the first `- [ ]` task whose earlier tasks in the same phase are done. Skip tasks marked for Vojta.
3. Make sure you are on the overnight branch (`git branch --show-current` starts with `overnight/`). Never switch to `main`.
4. Implement the task. Write or extend tests first where a criterion exists; make the referenced tests pass.
5. Run the checks: `cd backend && uv run pytest -q` and `uv run ruff check .`; when the frontend exists also
   `npm run -s typecheck --if-present && npm run -s lint --if-present` and the relevant Playwright specs.
   For UI tasks take a screenshot with the Playwright MCP or the e2e run into `logs/screens/`.
6. If everything passes: tick the task `- [x]`, add a Log line (newest first), `git add -A` (check that no `.env`,
   data or large files are staged), and `git commit -m "T<id>: <what>"`.
7. If you cannot finish within the iteration: commit what is safe (tests may be skipped/xfail with a reason, never
   deleted), mark `- [~]` with what remains in the Log.
8. If blocked (missing data, network, unclear requirement, needs a decision): mark `- [!]`, write a precise question for
   Vojta in the Log, and stop. Do not guess on decisions that are hard to undo.
9. Stop after one task. Print a 3-line summary: task, result, next task.

## Hard rules
- Do not push, deploy, `kubectl apply`, delete cluster resources, or change git remotes. The morning review does that.
- Do not read or print `.env`; do not hard-code keys. Do not commit data (`data/`, ADAR2 files, `*.parquet`).
- Do not weaken, delete or skip acceptance tests to make them pass. If a test contradicts `docs/api.md`, fix whichever is
  wrong, explain it in the Log, and keep both consistent.
- Keep dependencies modest; record every new dependency in the Log with a one-line reason.
- Live LLM tests (`-m live`) at most 3 runs per iteration (shared e-INFRA service, be nice).
- If the same test fails 3 attempts in a row with different fixes, stop and mark the task `- [~]` with your analysis.
- Long-running servers you start (uvicorn, vite) must be stopped before the iteration ends.
