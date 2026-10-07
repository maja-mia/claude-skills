---
name: agent-doc-consistency-review
description: Review Markdown documentation at a given path to check whether another AI agent can use it reliably as a guideline. Finds contradictions, ambiguity, missing context, and unclear or fake use cases, and checks code symbols the docs mention against the local code. Use when the user asks to review, audit, validate, or sanity-check .md docs, READMEs, library/module docs, design docs, or test-case files, especially docs written by or for agents.
argument-hint: <file.md | folder>
model: opus
context: fork
background: false
allowed-tools: Read, Glob, Grep, Write
disallowed-tools: Edit, Bash
---

# Agent doc consistency review

Target: `$ARGUMENTS`
Session ID: `${CLAUDE_SESSION_ID}`
Project root: `${CLAUDE_PROJECT_DIR}`

You are reviewing documentation that another AI agent will later use as its **only** source of truth for a piece of functionality, for example a library consumed by a different module. That agent can't ask the author questions. Anything ambiguous, contradictory, or implied will be guessed wrong or will make it stall. Review with that reader in mind.

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
- Resolve the target to an absolute path. An absolute target is used as is. A relative target is resolved against the current directory first; if nothing exists there, against the project root shown at the top (when it was filled in). If nothing exists at the resolved path, say so and stop. Use the resolved absolute path for every file operation.
- If the target is a single file, it must end in `.md`. If it doesn't, say so and stop.
- If the target is a folder, use Glob with `**/*.md` under that folder only. Skip anything inside `node_modules`, `dist`, `build`, `.git`, or `doc-reviews`, and skip `CHANGELOG.md`. Review all remaining files **together as one documentation set**, because contradictions between files are the most important thing to catch.
- If the folder contains no `.md` files to review, say so and stop.

## 2. Read everything before judging

Read every target file in full before writing any findings. Build a picture of what the docs claim: purpose, public API or entry points, use cases, constraints, defaults, and examples. Most contradictions only become visible once you hold the whole set at once.

## 3. Verify claims against the code

When the target names concrete code symbols (functions, components, hooks, exports, props, config keys, file paths, CLI commands), check that each one exists and matches what the docs describe: name, parameters, defaults, and import path.

How to search:
- Use Grep and Glob on the local files. Start in the target's own folder, then widen to the whole project root shown at the top, or the current directory if the project root wasn't filled in.
- Search code files only: exclude `*.md` from every Grep.
- To check a file path that points to a Markdown file, use Glob to confirm it exists. Don't open it.
- Check the files as they are on disk now, including uncommitted edits. Git history and remotes are out of scope: you have no shell, so don't try to reach them.

Which symbols to check:
- **Always:** every symbol used in a code example or an import statement.
- **Then:** up to 10 more symbols named only in prose. Prefer ones the docs describe as public API, required, or default behaviour.

Classify every checked symbol as exactly one of:
- **verified**: it exists and matches the docs.
- **contradicted**: it's missing or differs from the docs. Report each one as a Contradiction finding.
- **not verifiable**: the code isn't available locally or the match is ambiguous. Don't guess.

The three counts must add up to the total number of symbols checked.

## 4. Review on three axes

### A. Contradictions
- Statements that conflict within a file or across target files: different defaults, required vs optional, allowed vs forbidden, different names for the same thing, different behaviour for the same input.
- Examples that contradict the prose next to them.
- Contradicted symbols from step 3.
- Outdated content mixed with current content without saying which is which.

### B. Clarity for an agent
- Terms, acronyms, or internal names used without a definition.
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
<Agent-ready | Usable with fixes | Not agent-ready>. <1–2 sentences on the main reason.>

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
<one row per use case, or a single row: | none documented | – | – | – |>
```

Severity:
- **Critical:** an agent would very likely write wrong code or pick the wrong use case. This includes contradictions about behaviour, contradicted symbols, every use case marked **Unclear** in the inventory, and docs that describe no use case at all.
- **Major:** an agent would likely stall, guess, or need to read the source to proceed.
- **Minor:** wording or structure that slows down understanding without causing errors.

Verdict (apply mechanically, no judgment):
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

## 6. Save the report to a file (mandatory, before replying)

The report must survive even if the reply back to the main conversation is lost.

1. Build `<name>` from the target as typed (before resolving it): take its last path segment, drop a `.md` extension, and replace anything that isn't a letter, digit, `-`, or `_` with `-`. For example, `docs/my-lib.md` becomes `my-lib` and `docs/` becomes `docs`. If the result is empty or only dashes (for example, the target is `.`), use `root`.
2. The report path is `${CLAUDE_PROJECT_DIR}/doc-reviews/agent-doc-consistency-review_<name>_${CLAUDE_SESSION_ID}.md`. If the session ID or project root at the top is empty or still shows a literal `${...}` placeholder, use `session` for the ID and `./doc-reviews/` relative to the current directory.
3. Use Glob to check whether that path already exists (the same skill run twice in one session). If it does, insert `-2` before `.md`; if that exists too, try `-3`, and so on. Never overwrite an existing report.
4. Use the Write tool to save the **full report** in the step 5 structure to the final path. Write creates the folder if needed. Do this **before** sending any reply.
5. Then reply with only this short summary, not the full report:
   - the report file path
   - the verdict line
   - counts of Critical / Major / Minor findings
   - the titles of the Critical findings, one line each

If the Write fails, say so explicitly and put the full report in the reply instead, so it isn't lost.
