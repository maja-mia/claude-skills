---
name: agent-doc-consistency-review
description: Review Markdown documentation at one or more given paths to check whether another AI agent can use it reliably as a guideline. Finds contradictions, ambiguity, missing context, and unclear or fake use cases, and checks code symbols the docs mention against the local code. Use when the user asks to review, audit, validate, or sanity-check .md docs, READMEs, library/module docs, design docs, or test-case files, especially docs written by or for agents.
argument-hint: <path> [<path> ...]
model: opus
allowed-tools: Read, Write, Agent, Bash(find *), Bash(grep *), Bash(ls *), Bash(pwd)
disallowed-tools: Edit
---

# Agent doc consistency review

Targets, as typed: `$ARGUMENTS`
Session ID: `${CLAUDE_SESSION_ID}`
Project root: `${CLAUDE_PROJECT_DIR}`

You are reviewing documentation that another AI agent will later use as its **only** source of truth for a piece of functionality, for example a library consumed by a different module. That agent can't ask the author questions. Anything ambiguous, contradictory, or implied will be guessed wrong or will make it stall. Review with that reader in mind.

## How to run

- This skill runs inline in the user's session, so the user sees every step. Work through steps 1 to 7 in order.
- Keep a run log as you go: one line for each of steps 1 to 4, using the format in the `Run log` section of the report template. Record anything that didn't go as expected (a tool error, a denied call, a fallback you used, a file you couldn't read) with the exact reason.
- Step statuses in the run log mean exactly this:
  - Step 1: `done` once every target is resolved and the file list is known. A stop in step 1 writes no report, so it never appears as anything else.
  - Step 2: `done` if every target file was read in full; `partial` if at least one couldn't be read; `failed` if none could be read.
  - Step 3: `done` if every planned search ran, whatever the results. `partial` only if at least one search couldn't run (a denied or failed tool); `failed` if none could run. Symbols classified as not verifiable don't make step 3 partial.
  - Step 4: `done` or `not reached` only. It's reasoning, not tool use, so it can't be partial.
- Use your own tools for everything they can do. Never ask the user for something a tool can get, such as a file listing or file contents.
- Ask the user only when a step is genuinely ambiguous and no rule in this skill settles it. Ask one specific question, wait for the answer, record it in the run log, and continue.
- If a tool call is denied (by a hook, a permission rule, or the user rejecting a prompt), don't retry it: the answer won't change. Record the tool, the command, and the reason given in the run log right away, mark the step `failed` or `partial`, and continue where possible. In step 1, stop instead (see step 1). The Write in step 7 isn't part of the run log: a denied or failed Write is handled in step 7, item 5.
- If a tool fails for any other reason, retry once. If it fails again, record it in the run log, mark the step `failed` or `partial`, and continue with the remaining steps where possible. In step 1, stop instead (see step 1). Empty results are answers, not failures: an `ls` that reports "No such file or directory" during an existence check, a `grep` that finds nothing (exit code 1), and a `find` that prints nothing (exit code 0). Don't retry them or log them as failures. Real errors are exit code 2 from `grep` and any non-zero exit code from `find`; these follow the retry rule above.
- Exception, for step 3 only: when the only errors from a `grep` or `find` are "Permission denied" on some subfolders, don't retry (the result won't change) and don't mark the step `partial`. Use whatever it printed, and note the unreadable folders in the run log line for that step. Step 3 explains how this affects a symbol's classification. In step 1, "Permission denied" stops the review instead (see step 1).

### Shell rules

Searching and listing go through the Bash tool, because the dedicated Glob and Grep tools may not be available. Bash is for reading only:
- Use only `pwd`, `ls`, `find`, and `grep`.
- One simple command per call, on a single line. No pipes (`|` outside quotes; inside a quoted `grep -E` pattern it's fine), redirects (`>`, `<`), command chaining (`;`, `&&`, `||`), subshells (`$(...)`, backticks), or variables.
- Never use the `find` actions that change files or run commands: `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fprint`, `-fprint0`, `-fprintf`, `-fls`.
- Quote every path in double quotes.

## Scope and permissions

The review covers **only** the target paths, meaning the paths in the arguments: each target file, and the `.md` files inside each target folder and its subfolders. Nothing else is reviewed.

- Every finding, quote, and **Where** location must be in a file inside one of the target paths.
- Never open, review, quote, or report on any other Markdown file, even when a target links to it or it sits in a neighbouring folder.
- If a target depends on a document outside all the target paths and can't be understood without it, report that dependency as a Clarity finding in the target file, at the place where the link or reference appears.
- Reading outside the target paths is allowed in exactly two cases:
  1. Code lookups in step 3. That code is evidence for checking the targets' claims. Never report problems in the code itself.
  2. The existence check for the report file in step 7.
- Never edit, create, or delete any file except the single report file written in step 7.

## 1. Resolve the input

- If the arguments are empty, stop and reply only: `Usage: pass one or more Markdown files or folders as arguments, e.g. docs/my-lib.md docs/guides/. Put a path that contains spaces in double quotes.`
- Split the arguments into paths on spaces; a double-quoted part stays one path, even if it contains spaces. Each path is a target. If the same path appears more than once, keep it once.
- Resolve each target to an absolute path. An absolute target is used as is. A relative target is resolved against the current directory first (get it with `pwd`); if nothing exists there, against the project root shown at the top (when it was filled in). Check existence and type of each with `ls -ldL "<path>"` (`-L` reports what a symlink points to): output starting with `d` means a folder, output starting with `-` means a file. Use the resolved absolute path for every file operation.
- For each folder target, list its Markdown files with this command (one line):
  `find -H "<folder>" -type f -name '*.md' -not -path '*/node_modules/*' -not -path '*/dist/*' -not -path '*/build/*' -not -path '*/.git/*' -not -path '*/doc-reviews/*' -not -name CHANGELOG.md`
  If the listing reports "Permission denied" on any folder inside the target, the file list may be incomplete. Don't retry. Count the target as a problem and name every unreadable folder it reported.
- Check every target before stopping, so the reply can list all problems at once. A target is a problem if it doesn't exist, if it is a single file that doesn't end in `.md`, if it is a folder with no `.md` files to review, or if its folder listing hit "Permission denied".
- If there is at least one problem, stop and reply with every problem and its reason, and don't review the targets that were fine. This is an input error: don't write a report.
- Otherwise, merge the files of all file targets and all folder listings into one list, with duplicates removed (a file named directly and also found in a folder, or in two overlapping folders, counts once). These are the **target files**. Review all of them **together as one documentation set**, because contradictions between files are the most important thing to catch, including contradictions between different targets.
- A stop in this step is an input error: reply with the reasons only, and don't write a report. This includes any tool call in this step (`pwd`, `ls`, `find`) that is denied, or still fails after the one allowed retry.

## 2. Read everything before judging

Read every target file in full before writing any findings. Build a picture of what the docs claim: purpose, public API or entry points, use cases, constraints, defaults, and examples. Most contradictions only become visible once you hold the whole set at once.

## 3. Verify claims against the code

When the target files name concrete code symbols (functions, components, hooks, exports, props, config keys, file paths, CLI commands), check that each one exists and matches what the docs describe: name, import path, shape, return value, props, parameters, defaults, and behaviour.

How to search:
- Search with `grep` through Bash, following the shell rules. Start in the folder of each target (for a file target, its parent folder), then widen to the whole project root shown at the top, or the current directory if the project root wasn't filled in.
- Search code files only. Every search of the project's own code uses this form (one line): `grep -rn --exclude='*.md' --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=build --exclude-dir=.git --exclude-dir=doc-reviews '<pattern>' "<folder>"`. Add `-E` when the pattern needs alternation (`a|b`) or other extended regex.
- To find files by name, use `find -H` with the same `-not -path` exclusions as in step 1.
- Symbols from an external package are checked in the installed package, never in compiled code. A symbol is from an external package when the docs import it from a package name, unless that name is the project's own: the `name` in the `package.json` at the project root, or a path alias: a `paths` entry in `tsconfig.json` or in any file it lists under `references` or `extends`, or `resolve.alias` in the Vite config if there is one (read these with Read). Those are project code; search them as usual.
  1. Check that `<project root>/node_modules/<package>` exists with `ls -ldL "<project root>/node_modules/<package>"` (a scoped package is `@scope/name`). If it doesn't, every symbol from that package is **not verifiable**, and you record "`<package>` isn't installed" as the reason.
  2. If it exists, look for its type declarations with `find -H "<project root>/node_modules/<package>" -type f -name '*.d.ts'`. Don't use the `--exclude-dir=node_modules` or `-not -path '*/node_modules/*'` filters here, because they would hide everything. If it prints nothing, check that the folder `<project root>/node_modules/@types/<name>` exists with `ls -ldL` (for a scoped package `@scope/name`, the folder is `@types/scope__name`). Only if it exists, run the same `find` on it and use that folder as the package folder from here on. If that folder doesn't exist, or neither folder has any `.d.ts` file, every symbol from the package is **not verifiable**, with the reason "`<package>` ships no type declarations".
  3. Search the declarations with `grep -rn --include='*.d.ts' '<pattern>' "<package folder>"`.
  4. Type declarations settle a symbol's existence, import path, props, parameters, and types. They don't settle runtime behaviour, so a claim about behaviour is **not verifiable**.
  5. Stay inside that one package folder. A symbol the search doesn't find in the declarations is **not verifiable**, with the reason "not found in `<package>@<version>` declarations": declarations can take types from other packages, so a miss proves nothing. A symbol from an external package is **contradicted** only when it's found and a claim the docs make about it (import path, props, parameters, types) differs from the declarations.
  6. Read `package.json` in the package folder for its `version`, and give it in the symbol's Evidence (see the `Symbols checked` rules). It's the installed version, not the range the docs support. When the declarations came from the `@types` folder, the version is that folder's, and the label is `@types/<name>@<version>` instead of `<package>@<version>`.
  7. Apply this to every external package the docs use, the same way, whatever the package is. Never read anything else in `node_modules`.
- To check a claim beyond existence and name (import path, shape, return value, props, parameters, defaults, behaviour), open the code file with Read at the lines around the grep match. If reading the code doesn't settle a claim, that claim counts as not verifiable; the symbol's category then follows the precedence rule below.
- To check a file path that points to a Markdown file, use `ls "<path>"` to confirm it exists. Don't open it.
- Check the files as they are on disk now, including uncommitted edits. Git history and remotes are out of scope: `git` isn't allowed, so don't try to reach them.

A symbol is a name the docs say exists in code, because they show where it comes from: an import line, or prose that names it as code in this project or in an external package. A name the docs define themselves for the reader isn't a symbol, so don't check or count it. This covers a placeholder (such as a variable in an example standing for the reader's own value) and a helper the docs define in an example. A name with no import line that the docs neither define nor say exists in code (for example a hook used in an example with no import and no placeholder comment) isn't counted either. Report one Clarity finding in step 4 that lists every such name and every location where it appears: the docs don't say whether each is a placeholder or where it comes from. Don't decide this from search results.

Which symbols to check:
- **Always:** every symbol used in a code example or an import statement.
- **Then:** up to 10 more symbols named only in prose. Prefer ones the docs describe as public API, required, or default behaviour.

Classify every checked symbol as exactly one of:
- **verified**: it exists, and every claim the docs make about it matches the code.
- **contradicted**: any claim the docs make about it (existence, name, import path, shape, return value, props, parameters, defaults, or behaviour) differs from the code (for an external package's symbol, only the claims the `node_modules` rule says can be contradicted), or two statements in the docs about it conflict and the code settles which one is right. Report each contradicted symbol as one Critical Contradiction finding, listing every contradicting claim and every location in that one finding. Put the symbol's name in backticks in the finding's title.
- **not verifiable**: the code isn't available locally, the match is ambiguous, or reading the code doesn't settle a claim. Don't guess.

For a symbol the search found, if different claims about it lead to different categories, contradicted wins over not verifiable, and not verifiable wins over verified. A symbol the search didn't find is classified only by the test below, or, for an external package's symbol, by the `node_modules` rule.

When a search finds nothing, decide between these two with one test: does the code the symbol should belong to exist locally (its module, file, or component folder)? If yes, the symbol is **contradicted**. If that code isn't in the project at all (for example, an external package that isn't installed, or another service), it's **not verifiable**. For a symbol from an external package, don't use this test: the `node_modules` rule above applies: a miss there is always **not verifiable**. If the search hit "Permission denied" on a subfolder, a symbol it found is classified as usual, but a symbol it didn't find is **not verifiable**, because it might be in the folder that couldn't be read.

The three counts must add up to the total number of symbols checked.

## 4. Review on three axes

### A. Contradictions
A contradiction means two statements can't both be true at once. A statement that's only less detailed than another, but compatible with it, is not a contradiction: report it under Clarity.
- Statements that conflict within a file or across target files: different defaults, required vs optional, allowed vs forbidden, different behaviour for the same input.
- Different spellings of the same code identifier (function, prop, config key, file path), for example `fetchItems` in one doc and `fetchItem` in another.
- Examples that contradict the prose next to them.
- Contradicted symbols from step 3.
- Outdated statements that conflict with current ones.

Report each problem once. If step 3 already counted a symbol as contradicted, that one finding covers every location where the docs get it wrong, including conflicts between docs that the code settles: don't add a second finding for it here. A claim about a symbol that differs from the code is never a Clarity finding on its own: it goes into that symbol's Critical finding. This includes a description the docs present as complete, or that is false for some input (for example a list of steps that leaves out a step the code performs, so a stated outcome is wrong in some case). A description that is only less detailed than the code, and still true for every input, is not a contradiction: report it under Clarity.

### B. Clarity for an agent
- Terms, acronyms, or internal names used without a definition.
- Different words for the same concept, for example "config" in one place and "settings" in another.
- Vague words where the agent needs a rule: "usually", "should probably", "in most cases", "etc.", "and so on", "as needed", "appropriately".
- Implicit knowledge: steps that assume the reader knows the project, the team's conventions, or context from a conversation that isn't written down.
- References such as "above", "the previous section", "the old way", or "like before" that are ambiguous or point to nothing.
- Pronouns or phrases where it's unclear what they refer to.
- Dependencies on documents outside the target paths (see Scope).
- Code examples that are incomplete in a way that matters: missing imports, unknown variables, `...` hiding essential parts, placeholder values not marked as placeholders. Names the docs use without an import or a definition are reported once, in the single finding that step 3 describes: don't list them again here.

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
# Agent doc consistency review: <targets, comma-separated>

Files reviewed: <list>

## Verdict
<Agent-ready | Usable with fixes | Not agent-ready | Incomplete>. <1–2 sentences on the main reason.>
Independent check: <done — N confirmed, N corrected, N removed, N unchecked | not done — reason | not needed — no Critical or Major findings>

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
<one row per use case; or a single row: | none documented | – | – | – |>

## Symbols checked
| Symbol | Status | Evidence |
|---|---|---|
<one row per checked symbol, contradicted first, then not verifiable, then verified; or a single row: | none | – | – |>

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

Rules for the inventory:
- Each cell holds exactly one value, and the "Real / Illustrative / Unclear" cell is exactly one of those three words. "Complete example?" is exactly `Yes`, `No`, or `Partial (<what's missing>)`; only `Partial` has a note. If one use case is partly real and partly illustrative, or has examples of different completeness, split it into one row per part.
- Every row with `No` or `Partial` must be covered by a finding whose **Where** points to that row's section.

Rules for the `Symbols checked` table:
- One row per symbol counted in the `Code verification` line, so the rows add up to the same total and to the same three counts.
- **Status** is exactly `verified`, `contradicted`, or `not verifiable`.
- **Evidence** is, for `verified`, the `file:line` of the code that settles it, followed for an external package's symbol by `<package>@<installed version>`; for `contradicted`, the exact title of the one Critical finding that covers it; for `not verifiable`, exactly one of these reasons:
  - For an external package's symbol: "`<package>` isn't installed"; "`<package>` ships no type declarations"; "not found in `<package>@<version>` declarations" (a symbol the declarations don't contain, which may be a typo); "behaviour isn't visible in the type declarations" (a claim the types can't settle). Keep the last two apart.
  - For a symbol in the project's own code: "ambiguous match" (more than one place in the project's code matches); "code doesn't settle the claim" (reading the code at the match doesn't settle it); "code isn't in this project" (for example another service); "search hit Permission denied on `<folder>`" (the symbol wasn't found, and the search couldn't read that folder).

Rules for the report:
- Show every file path in the report (title, Files reviewed, Where, inventory) relative to the project root (or the current directory if the project root wasn't filled in).
- Order findings Critical, then Major, then Minor.
- For a contradiction, list every location involved under **Where**.
- Quote the actual text. Every finding must point to a specific location inside one of the target paths.
- Give fixes as concrete replacement text or concrete missing facts, not "clarify this".
- Don't invent facts to fill gaps. If the right answer is unknown, put it under **Missing information** as a question for the author.
- A **Fix** may state only what you verified in the target files or the code. If it depends on a question listed under **Missing information**, word that part conditionally ("if X, then …") or leave it out. Don't describe what a file contains if you only checked that it exists. When the fix is "add the missing fact", name the fact; don't write "add a sentence about it".
- Don't report style nitpicks (tone, formatting preferences) unless they cause misreading.
- If an axis has no issues, list it by its exact name in the `No issues found on` line rather than padding findings.

## 6. Check the report before saving

Before step 7, go through this checklist once against the report you drafted. Fix every failed item in the report, then continue. Don't put the checklist or its results in the report, and don't add a line for it to the run log. If you stopped early, check only the parts the report has.

1. The three counts add up to the total in the `Code verification` line, and the `Symbols checked` table has exactly that many rows.
2. Every symbol used in a code example or import statement is in the table. Every name in the table is a symbol by the step 3 definition (not a placeholder or a helper the docs define).
3. Every `contradicted` row names the exact title of one Critical finding, and that finding's title names the symbol in backticks. No symbol has a second finding.
4. Every inventory cell follows the inventory rules, and every `No` or `Partial` row is covered by a finding.
5. Every finding has all five fields, and each **Where** is inside the target paths. Findings are ordered Critical, Major, Minor.
6. Every **Fix** states only verified facts (see the report rules), and the verdict follows the verdict rules from the run log and the findings.

### Independent check of the findings

When the checklist passes, have the `finding-verifier` agent (`doc-review:finding-verifier`) check every Critical and Major finding. If there are none, or the verdict is `Incomplete`, skip this and write `not needed — no Critical or Major findings` or `not done — verdict is Incomplete` on the `Independent check` line.

1. Number the Critical and Major findings F1, F2, … in report order. Make one call to the agent with all of them in one task message. For each finding give: its number, severity, axis, title, Quote, Problem, Fix, and the line ranges to read, as `path:start-end`. Use the documentation ranges from its **Where** (the whole section when **Where** gives only a heading) and the code ranges you relied on in step 3. Give the facts only, not your reasoning, and don't tell it what answer you expect.
2. The agent may run in the background and answer in a later turn. Don't write the report until its answer has arrived, or until you've decided it failed. If the user tells you to continue without it, use `not done — no answer received`.
3. Apply its answers:
   - `confirmed`: keep the finding.
   - `overstated`: rewrite the finding with its `Corrected` wording or severity.
   - `wrong`: remove the finding. If it was a contradicted symbol's finding, reclassify the symbol by the step 3 rules, then update the counts, the `Symbols checked` row, and the verdict.
   - `unchecked`: keep the finding as it is.
4. After applying the answers, go through checklist items 1, 3, 4, and 6 again for whatever changed. Then write the `Independent check` line, for example `done — 4 confirmed, 2 corrected, 1 removed, 0 unchecked`.
5. If the call is denied, fails, or returns nothing usable, retry once at most, then continue without it and write `not done — <the exact reason>`. This never changes the verdict. Don't add a line for this check to the run log.

## 7. Save the report to a file (mandatory)

The report file is the record of the review, including how the run went. Always write it once step 1 has passed, even if a later step failed or you had to stop early. In that case, fill in what you have, mark the rest `not reached` in the run log, and use the `Incomplete` verdict.

1. Build `<name>` from the first target as typed (before resolving it): take its last path segment, drop a `.md` extension, and replace anything that isn't a letter, digit, `-`, or `_` with `-`. For example, `docs/my-lib.md` becomes `my-lib` and `docs/` becomes `docs`. If the result is empty or only dashes (for example, the first target is `.`), use `root`. With more than one target, append `-plus-<N-1>`, where N is the number of targets: three targets starting with `docs/guides/` give `guides-plus-2`.
2. The report path is `${CLAUDE_PROJECT_DIR}/doc-reviews/agent-doc-consistency-review_<name>_${CLAUDE_SESSION_ID}.md`. If the session ID or project root at the top is empty or still shows a literal `${...}` placeholder, use `session` for the ID and `./doc-reviews/` relative to the current directory.
3. Use `ls "<path>"` to check whether that path already exists (the same skill run twice in one session). If it does, insert `-2` before `.md`; if that exists too, try `-3`, and so on. Never overwrite an existing report.
4. Write the report:
   - **If the user's own instructions require confirmation before writing files:** first send a message that contains the **full report** in the step 5 structure and asks for confirmation, so the report is in the chat whatever happens next. Then wait. If the user confirms, write the file. If the user declines, reply that the report wasn't saved and stop. Don't ask again.
   - **Otherwise:** write the file right away.
   - Use the Write tool to save the full report to the final path. Write creates the folder if needed.
5. End with exactly one of these replies:
   - **Written without asking:** only this short summary, not the full report:
     - the report file path
     - the verdict line and the `Independent check` line
     - counts of Critical / Major / Minor findings
     - the titles of the Critical findings, one line each
     - every run-log line that isn't `done`
   - **Written after confirmation:** only the report file path. The full report is already in the chat.
   - **Write denied, or failed after the one retry allowed for non-denial errors:** say the report couldn't be saved and give the reason. If the full report isn't in the chat yet, include it in this reply so it isn't lost.
