You are running unattended as part of an overnight loop on the Aibex View repo. Follow docs/overnight.md exactly.
Do ONE task from PROGRESS.md (the first `[~]`, else the first `[ ]` task whose `after:` tasks are done, skipping tasks marked "– Vojta"),
make its acceptance tests pass (docs/acceptance.md, contracts in docs/api.md), run the checks (`make test`, `make accept-phase P=<n>`, `make e2e` for UI tasks), update PROGRESS.md
(tick + Log line, newest first), commit on the current overnight/ branch, then stop with a 3-line summary.
If every remaining task is done or blocked, write a short status to the Log, commit, and reply exactly: ALL_TASKS_DONE_OR_BLOCKED
