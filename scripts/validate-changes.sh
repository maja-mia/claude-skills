#!/usr/bin/env sh
# Local only: run `claude plugin validate` on every plugin and skill changed compared to main and
# write each one's validation-report.json. Needs your own `claude` CLI; CI only checks the reports.
# Optional: --base <branch> to compare against something else than origin/main (or main).
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)

exec python3 "${repo_root}/ci/ci.py" --repo "${repo_root}" "$@" validate
