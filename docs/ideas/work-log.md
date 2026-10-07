# work-log ideas

## Narrowing the repository scope

No GitHub issue filed yet.

Today the skill searches without an owner filter: `SKILL.md` passes no `--owner`, so the search is
not limited to one organization. The script already supports `--owner <org>`, which it turns into
the `org:<org>` search qualifier.

Idea: let the user narrow the scope when calling the skill.

- **Specific organization**: pass an org name, e.g. `/work-log:work-log 2026-09-01 2026-09-30 some-org`
  → `--owner some-org`.
- **Default** stays unrestricted when nothing is passed.

To do:

- [ ] Add an optional third argument (e.g. `scope`) to the `arguments` / `argument-hint`
      frontmatter in `SKILL.md` and map it to `--owner <org>`.
- [ ] Optionally allow several orgs (`--owner` repeated → `org:a org:b`); check in GitHub's search
      docs how multiple `org:` qualifiers combine before implementing.
- [ ] Show the scope in the rendered log header (already shown for a single owner).
- [ ] Tests for query building with multiple owners.
- [ ] Verify against real data that the `org:` filter actually excludes commits from other owners
      (not yet tested).
- [ ] Update README usage.
