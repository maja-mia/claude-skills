---
name: work-log
description: Build a per-day work log (what you did each day, with that day's commits) from your GitHub commits for a date range — for the mandatory time-tracking entries.
argument-hint: "[from YYYY-MM-DD] [to YYYY-MM-DD]"
arguments: [from, to]
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/work_log.py *) Bash(mktemp -d*)
---

Produce a Markdown work log of the user's GitHub commits from `$from` to `$to`.

If either date is missing or not a `YYYY-MM-DD` date, ask the user for the range before doing
anything (convert phrases like "last month" to explicit dates and confirm them).

1. Create a working directory with `mktemp -d` and call it `WORKDIR`.
2. Fetch the commits (read-only GitHub search as the `gh`-logged-in user, `cirql-one` repos only;
   drop `--owner` only if the user asks for all their repositories):

   ```
   python3 ${CLAUDE_SKILL_DIR}/scripts/work_log.py fetch $from $to --owner cirql-one --out WORKDIR/commits.json
   ```

   stdout is a digest: one `## YYYY-MM-DD` heading per day with commits, the repositories as
   `[repo]`, and commit subjects beneath (`merged:` lines are pull-request titles). If the command
   fails, show the user its error message and stop — typical fixes are `gh auth login` or a
   narrower range.
3. Write `WORKDIR/summaries.json`: a JSON object with **one entry for every day in the digest**,
   `{"YYYY-MM-DD": "summary"}`. Each summary is 1–2 sentences in English describing the work that
   day — the feature, fix or area worked on, and in which repositories — written for a timesheet,
   not a commit-by-commit retelling. Keep ticket IDs (e.g. `ENG-142`) that appear in the commits.
   Use only what the commit messages say; don't invent purpose or outcomes.
4. Render the log into the user's current directory:

   ```
   python3 ${CLAUDE_SKILL_DIR}/scripts/work_log.py render --commits WORKDIR/commits.json --summaries WORKDIR/summaries.json --out work-log-FROM_TO.md
   ```

   with `FROM` and `TO` replaced by the two dates.

   If it reports days with missing summaries, add them and rerun.
5. Tell the user the output path, then briefly:
   - the weekdays with no commits (listed at the top of the file) — they need filling from other
     sources (Linear, Notion, meetings) or marking as leave;
   - any weekend days that have commits;
   - that only commits on repositories' default branches are included (GitHub search limitation),
     so unmerged branch work is missing.
