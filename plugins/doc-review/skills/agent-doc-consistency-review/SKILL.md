---
name: agent-doc-consistency-review
description: Review Markdown documentation at a given path to check whether another AI agent can use it reliably as a guideline. Finds contradictions, ambiguity, missing context, and unclear or fake use cases, and checks code symbols the docs mention against the local code. Use when the user asks to review, audit, validate, or sanity-check .md docs, READMEs, library/module docs, design docs, or test-case files, especially docs written by or for agents.
argument-hint: <file.md | folder>
model: opus
allowed-tools: Read, Write, Bash(find *), Bash(grep *), Bash(ls *), Bash(pwd)
disallowed-tools: Edit
---

# Agent doc consistency review

Target: `$ARGUMENTS`
Session ID: `${CLAUDE_SESSION_ID}`
Project root: `${CLAUDE_PROJECT_DIR}`

You are reviewing documentation that another AI agent will later use as its **only** source of truth for a piece of functionality, for example a library consumed by a different module. That agent can't ask the author questions. Anything ambiguous, contradictory, or implied will be guessed wrong or will make it stall. Review with that reader in mind.

## How to run

- This skill runs inline in the user's session, so the user sees every step. Work through steps 1 to 6 in order.
- Keep a run log as you go: one line for each of steps 1 to 4, using the format in the `Run log` section of the report template. Record anything that didn't go as expected (a tool error, a denied call, a fallback you used, a file you couldn't read) with the exact reason.
- Step statuses in the run log mean exactly this:
  - Step 1: `done` once the target is resolved and the file list is known. A stop in step 1 writes no report, so it never appears as anything else.
  - Step 2: `done` if every target file was read in full; `partial` if at least one couldn't be read; `failed` if none could be read.
  - Step 3: `done` if every planned search ran, whatever the results. `partial` only if at least one search couldn't run (a denied or failed tool); `failed` if none could run. Symbols classified as not verifiable don't make step 3 partial.
  - Step 4: `done` or `not reached` only. It's reasoning, not tool use, so it can't be partial.
- Use your own tools for everything they can do. Never ask the user for something a tool can get, such as a file listing or file contents.
- Ask the user only when a step is genuinely ambiguous and no rule in this skill settles it. Ask one specific question, wait for the answer, record it in the run log, and continue.
- If a tool call is denied (by a hook, a permission rule, or the user rejecting a prompt), don't retry it: the answer won't change. Record the tool, the command, and the reason given in the run log right away, mark the step `failed` or `partial`, and continue where possible. In step 1, stop instead (see step 1). The Write in step 6 isn't part of the run log: a denied or failed Write is handled in step 6, item 5.
- If a tool fails for any other reason, retry once. If it fails again, record it in the run log, mark the step `failed` or `partial`, and continue with the remaining steps where possible. In step 1, stop instead (see step 1). Empty results are answers, not failures: an `ls` that reports "No such file or directory" during an existence check, a `grep` that finds nothing (exit code 1), and a `find` that prints nothing (exit code 0). Don't retry them or log them as failures. Real errors are exit code 2 from `grep` and any non-zero exit code from `find`; these follow the retry rule above.
- Exception, for step 3 only: when the only errors from a `grep` or `find` are "Permission denied" on some subfolders, don't retry (the result won't change) and don't mark the step `partial`. Use whatever it printed, and note the unreadable folders in the run log line for that step. Step 3 explains how this affects a symbol's classification. In step 1, "Permission denied" stops the review instead (see step 1).

### Shell rules

Searching and listing go through the Bash tool, because the dedicated Glob and Grep tools may not be available. Bash is for reading only:
- Use only `pwd`, `ls`, `find`, and `grep`.
- One simple command per call, on a single line. No pipes (`|` outside quotes; inside a quoted `grep -E` pattern it's fine), redirects (`>`, `<`), command chaining (`;`, `&&`, `||`), subshells (`$(...)`, backticks), or variables.
- Never use the `find` actions that change files or run commands: `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fprint`, `-fprint0`, `-fprintf`, `-fls`.
- Quote every path in double quotes.

## Scope and permissions

The review covers **only** the target path: that one file, or the `.md` files inside that folder and its subfolders. Nothing else is reviewed.

- Every finding, quote, and **Where** location must be in a file inside the target path.
- Never open, review, quote, or report on any other Markdown file, even when the target links to it or it sits in a neighbouring folder.
- If the target depends on a document outside the path and can't be understood without it, report that dependency as a Clarity finding in the target file, at the place where the link or reference appears.
- Reading outside the target path is allowed in exactly two cases:
  1. Code lookups in step 3. That code is evidence for checking the target's claims. Never report problems in the code itself.
  2. The existence check for the report file in step 6.
- Never edit, create, or delete any file except the single report file written in step 6.

## 1. Resolve the input

- If the target is empty, stop and reply only: `Usage: pass a single Markdown file or a folder of Markdown files as the argument, e.g. docs/my-lib.md or docs/`.
- Resolve the target to an absolute path. An absolute target is used as is. A relative target is resolved against the current directory first (get it with `pwd`); if nothing exists there, against the project root shown at the top (when it was filled in). Check existence and type with `ls -ldL "<path>"` (`-L` reports what a symlink points to): output starting with `d` means a folder, output starting with `-` means a file. If nothing exists at the resolved path, say so and stop. Use the resolved absolute path for every file operation.
- If the target is a single file, it must end in `.md`. If it doesn't, say so and stop.
- If the target is a folder, list its Markdown files with this command (one line), and review only what it returns:
  `find -H "<folder>" -type f -name '*.md' -not -path '*/node_modules/*' -not -path '*/dist/*' -not -path '*/build/*' -not -path '*/.git/*' -not -path '*/doc-reviews/*' -not -name CHANGELOG.md`
  Review all of them **together as one documentation set**, because contradictions between files are the most important thing to catch.
- If the folder listing reports "Permission denied" on any folder inside the target, the file list may be incomplete. Don't retry. Stop and reply with every unreadable folder it reported. This is an input error: don't write a report.
- If the folder contains no `.md` files to review, say so and stop.
- A stop in this step is an input error: reply with the reason only, and don't write a report. This includes any tool call in this step (`pwd`, `ls`, `find`) that is denied, or still fails after the one allowed retry.

## 2. Read everything before judging

Read every target file in full before writing any findings. Build a picture of what the docs claim: purpose, public API or entry points, use cases, constraints, defaults, and examples. Most contradictions only become visible once you hold the whole set at once.

## 3. Verify claims against the code

When the target names concrete code symbols (functions, components, hooks, exports, props, config keys, file paths, CLI commands), check that each one exists and matches what the docs describe: name, import path, shape, return value, props, parameters, defaults, and behaviour.

How to search:
- Search with `grep` through Bash, following the shell rules. Start in the target's own folder, then widen to the whole project root shown at the top, or the current directory if the project root wasn't filled in.
- Search code files only. Every search uses this form (one line): `grep -rn --exclude='*.md' --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=build --exclude-dir=.git --exclude-dir=doc-reviews '<pattern>' "<folder>"`. Add `-E` when the pattern needs alternation (`a|b`) or other extended regex.
- To find files by name, use `find -H` with the same `-not -path` exclusions as in step 1.
- To check a claim beyond existence and name (import path, shape, return value, props, parameters, defaults, behaviour), open the code file with Read at the lines around the grep match. If reading the code doesn't settle a claim, that claim counts as not verifiable; the symbol's category then follows the precedence rule below.
- To check a file path that points to a Markdown file, use `ls "<path>"` to confirm it exists. Don't open it.
- Check the files as they are on disk now, including uncommitted edits. Git history and remotes are out of scope: `git` isn't allowed, so don't try to reach them.

Which symbols to check:
- **Always:** every symbol used in a code example or an import statement.
- **Then:** up to 10 more symbols named only in prose. Prefer ones the docs describe as public API, required, or default behaviour.

Classify every checked symbol as exactly one of:
- **verified**: it exists, and every claim the docs make about it matches the code.
- **contradicted**: any claim the docs make about it (existence, name, import path, shape, return value, props, parameters, defaults, or behaviour) differs from the code. Report each contradicted symbol as one Critical Contradiction finding, listing every contradicting claim and every location in that one finding.
- **not verifiable**: the code isn't available locally, the match is ambiguous, or reading the code doesn't settle a claim. Don't guess.

For a symbol the search found, if different claims about it lead to different categories, contradicted wins over not verifiable, and not verifiable wins over verified. A symbol the search didn't find is classified only by the test below.

When a search finds nothing, decide between these two with one test: does the code the symbol should belong to exist locally (its module, file, or component folder)? If yes, the symbol is **contradicted**. If that code isn't in the project at all (for example, an external package or another service), it's **not verifiable**. If the search hit "Permission denied" on a subfolder, a symbol it found is classified as usual, but a symbol it didn't find is **not verifiable**, because it might be in the folder that couldn't be read.

The three counts must add up to the total number of symbols checked.

## 4. Review on three axes

### A. Contradictions
A contradiction means two statements can't both be true at once. A statement that's only less detailed than another, but compatible with it, is not a contradiction: report it under Clarity.
- Statements that conflict within a file or across target files: different defaults, required vs optional, allowed vs forbidden, different behaviour for the same input.
- Different spellings of the same code identifier (function, prop, config key, file path), for example `useBreadcrumbs` in one doc and `useBreadcrumb` in another.
- Examples that contradict the prose next to them.
- Contradicted symbols from step 3.
- Outdated statements that conflict with current ones.

Report each problem once. If step 3 already counted a symbol as contradicted, that one finding covers every location where the docs get it wrong, including conflicts between docs: don't add a second finding for it here.

### B. Clarity for an agent
- Terms, acronyms, or internal names used without a definition.
- Different words for the same concept, for example "config" in one place and "settings" in another.
- Vague words where the agent needs a rule: "usually", "should probably", "in most cases", "etc.", "and so on", "as needed", "appropriately".
- Implicit knowledge: steps that assume the reader knows the project, the team's conventions, or context from a conversation that isn't written down.
- References such as "above", "the previous section", "the old way", or "like before" that are ambiguous or point to nothing.
- Pronouns or phrases where it's unclear what they refer to.
- Dependencies on documents outside the target path (see Scope).
- Code examples that are incomplete in a way that matters: missing imports, unknown variables, `...` hiding essential parts, placeholder values not marked as placeholders.

### C. Usability as a guideline
This is the axis that matters most. The typical failure is an agent that reads the docs and still can't tell **what a real use case is**.
- **Real vs illustrative:** is every use case or example clearly marked as an actual supported use case, or as a hypothetical or illustrative one? Raise a Critical finding on the Guideline usability axis for each use case marked Unclear in the inventory. If the docs describe no use case at all, raise one Critical finding on the Guideline usability axis for that instead.
- **Decision rules:** does the doc say *when* to use this functionality and *when not to*? If there are alternatives, is the choice between them explicit?
- **Supported vs internal:** is it clear which parts are the public, stable surface for consumers and which are internal implementation details?
- **Current vs planned:** is planned, deprecated, or experimental functionality clearly separated from what works today?
- **Actionability:** for each use case, could an agent go from the doc to working code without guessing? Is there one complete example per use case?
- **Constraints and failure modes:** are limits, preconditions, error behaviour, and "don't do this" rules stated explicitly?
- **Scope of the functionality:** does the doc say what the functionality is *not* for?

## 5. Report format

Write the report in exactly this structure:

```
# Agent doc consistency review: <target>

Files reviewed: <list>

## Verdict
<Agent-ready | Usable with fixes | Not agent-ready | Incomplete>. <1–2 sentences on the main reason.>

## Findings

Code verification: <N> symbols checked: <V> verified, <X> contradicted, <M> not verifiable.
No issues found on: <comma-separated axis names with no findings (Contradiction, Clarity, Guideline usability), or "none">.

### [Critical|Major|Minor] <short title>
- **Where:** <file>:<line or section heading>
- **Axis:** Contradiction | Clarity | Guideline usability
- **Quote:** "<the exact problematic text, kept short>"
- **Problem:** <why an agent would misread this or get stuck>
- **Fix:** <concrete rewrite or the exact information that needs to be added>

## Missing information
<Questions an agent would need answered that the docs don't answer at all. One line each, or "none".>

## Use-case inventory
| Use case | Real / Illustrative / Unclear | Complete example? | Where |
|---|---|---|---|
<one row per use case, with "Complete example?" as Yes, No, or Partial (<what's missing>); or a single row: | none documented | – | – | – |>

## Run log
<one line for each of steps 1–4: "<step number>. <step name>: done | partial | failed | not reached — <what happened, with the exact reason for anything other than done>">
```

Severity:
- **Critical:** an agent would very likely write wrong code or pick the wrong use case. This includes every Contradiction finding (as defined in 4A), every use case marked **Unclear** in the inventory, and docs that describe no use case at all.
- **Major:** an agent would likely stall, guess, or need to read the source to proceed.
- **Minor:** wording or structure that slows down understanding without causing errors.

Verdict (apply mechanically, no judgment):
- **Incomplete** if any of steps 2, 3, or 4 is `partial`, `failed`, or `not reached` in the run log. This overrides the rules below, because the findings can't be trusted as complete.
- **Not agent-ready** if there is at least one Critical finding.
- **Usable with fixes** if there are Major findings but no Critical ones.
- **Agent-ready** otherwise.

Rules for the report:
- Show every file path in the report (title, Files reviewed, Where, inventory) relative to the project root (or the current directory if the project root wasn't filled in).
- Order findings Critical, then Major, then Minor.
- For a contradiction, list every location involved under **Where**.
- Quote the actual text. Every finding must point to a specific location inside the target path.
- Give fixes as concrete replacement text or concrete missing facts, not "clarify this".
- Don't invent facts to fill gaps. If the right answer is unknown, put it under **Missing information** as a question for the author.
- Don't report style nitpicks (tone, formatting preferences) unless they cause misreading.
- If an axis has no issues, list it by its exact name in the `No issues found on` line rather than padding findings.

## 6. Save the report to a file (mandatory)

The report file is the record of the review, including how the run went. Always write it once step 1 has passed, even if a later step failed or you had to stop early. In that case, fill in what you have, mark the rest `not reached` in the run log, and use the `Incomplete` verdict.

1. Build `<name>` from the target as typed (before resolving it): take its last path segment, drop a `.md` extension, and replace anything that isn't a letter, digit, `-`, or `_` with `-`. For example, `docs/my-lib.md` becomes `my-lib` and `docs/` becomes `docs`. If the result is empty or only dashes (for example, the target is `.`), use `root`.
2. The report path is `${CLAUDE_PROJECT_DIR}/doc-reviews/agent-doc-consistency-review_<name>_${CLAUDE_SESSION_ID}.md`. If the session ID or project root at the top is empty or still shows a literal `${...}` placeholder, use `session` for the ID and `./doc-reviews/` relative to the current directory.
3. Use `ls "<path>"` to check whether that path already exists (the same skill run twice in one session). If it does, insert `-2` before `.md`; if that exists too, try `-3`, and so on. Never overwrite an existing report.
4. Write the report:
   - **If the user's own instructions require confirmation before writing files:** first send a message that contains the **full report** in the step 5 structure and asks for confirmation, so the report is in the chat whatever happens next. Then wait. If the user confirms, write the file. If the user declines, reply that the report wasn't saved and stop. Don't ask again.
   - **Otherwise:** write the file right away.
   - Use the Write tool to save the full report to the final path. Write creates the folder if needed.
5. End with exactly one of these replies:
   - **Written without asking:** only this short summary, not the full report:
     - the report file path
     - the verdict line
     - counts of Critical / Major / Minor findings
     - the titles of the Critical findings, one line each
     - every run-log line that isn't `done`
   - **Written after confirmation:** only the report file path. The full report is already in the chat.
   - **Write denied, or failed after the one retry allowed for non-denial errors:** say the report couldn't be saved and give the reason. If the full report isn't in the chat yet, include it in this reply so it isn't lost.
