# claude-skills

Internal [Claude Code plugin marketplace](https://code.claude.com/docs/en/plugins/create-marketplace)
for Cirql One. Private repo — only people with read access to it can install from it.

## Install

Prerequisites on your machine:

- Claude Code
- `python3` 3.9 (the version CI tests; newer ones should work too)
- GitHub CLI, logged in and set up as git credential helper (Claude Code clones this private repo
  with your own git credentials and can't prompt for them):

  ```sh
  gh auth login
  gh auth setup-git
  ```

Then, in Claude Code:

```
/plugin marketplace add cirql-one/claude-skills
/plugin install work-log@cirql-one
```

Updates: run `/plugin marketplace update cirql-one`, or turn on auto-update for the marketplace
under **Marketplaces** in `/plugin`.

## Plugins

### work-log

Builds a per-day work log for the mandatory time tracking: a 1–2 sentence summary of what you did
each day plus that day's commits (time, repo, linked SHA, message).

```
/work-log:work-log 2026-09-01 2026-09-30
```

It writes `work-log-<from>_<to>.md` to your current directory. The commits come from GitHub
commit search, read-only, for the logged-in `gh` user in `cirql-one` repositories.

Limits to know:

- Only commits on repositories' **default branches** are found (GitHub search limitation), so
  unmerged branch work is missing.
- Days are your local calendar days, taken from each commit's author time zone.
- Weekdays without commits are listed at the top of the file; fill them from Linear/Notion or mark
  them as leave.
- The summaries are written by Claude from commit messages only — review them before submitting.

## Development

Two scripts, both run from the repo root:

- `./scripts/test.sh` runs the same checks as CI, in Docker, on Python 3.9. It runs the unit
  tests of every skill and of `ci/`, enforces 90% branch coverage, and checks the validation
  reports (below).
- `./scripts/validate-changes.sh` writes the validation reports. It runs locally only.

### Prerequisites

- **`test.sh`:** Docker Desktop, running, which is all it needs: no Python, no packages. The first
  run needs network access to pull the Python image. The repo must be a git checkout with a `main`
  or `origin/main` branch.
- **`validate-changes.sh`:** `python3` 3.9, `git` and the Claude Code CLI v2.1.259 or later.
  Docker Desktop provides none of them.
- **CI:** nothing. GitHub's Ubuntu 24.04 runner has Docker preinstalled.

### Validation reports

Every plugin and skill that changed compared to `main` needs a `validation-report.json` in its own
folder, and the report must have passed and be written after your last edit. CI fails on a missing,
failed or stale report.

`./scripts/validate-changes.sh` writes them: it runs `claude plugin validate` on each changed
plugin and skill. Commit the reports with your change. Editing again makes them stale, so rerun
the script. CI never runs `claude`; it only checks the reports.

Try local changes without pushing: `claude plugin marketplace add ./` from the repo root, then
install as above; edits load at the next session or on `/reload-plugins`.

**Releasing:** bump `version` in `plugins/work-log/.claude-plugin/plugin.json` — users only receive
changes when the version string changes.

**Ideas:** planned improvements live in `docs/ideas/<plugin>.md`, each linked to a GitHub issue.
