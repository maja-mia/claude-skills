# work-log ideas

## Configurable repository scope

Tracked in [#1](https://github.com/cirql-one/claude-skills/issues/1).

Today the skill always searches only `cirql-one` repositories: `SKILL.md` hardcodes
`--owner cirql-one`, which the script turns into the `org:cirql-one` search qualifier.

Idea: let the user choose the scope when calling the skill.

- **Specific organization**: pass an org name, e.g. `/work-log:work-log 2026-09-01 2026-09-30 other-org`
  → `--owner other-org`.
- **All repositories**: e.g. `all` → no `--owner`, so the search covers every repository the user's
  `gh` login can see (personal repos, other orgs, public projects).
- **Default** stays `cirql-one` when nothing is passed.

To do:

- [ ] Add an optional third argument (e.g. `scope`) to the `arguments` / `argument-hint`
      frontmatter in `SKILL.md` and map it to `--owner <org>` / no `--owner`.
- [ ] Optionally allow several orgs (`--owner` repeated → `org:a org:b`); check in GitHub's search
      docs how multiple `org:` qualifiers combine before implementing.
- [ ] Show the scope in the rendered log header (already shown for a single owner).
- [ ] Tests for query building with no owner / multiple owners.
- [ ] Verify against real data that the `org:` filter actually excludes commits from other owners
      (not yet tested — all current test data happened to be in `cirql-one`).
- [ ] Update README usage.
