"""Tests for work_log.py. Run: python3 -m unittest discover -s <this directory>"""
from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import work_log
from work_log import Commit, CommitSet, WorkLogError


def search_item(sha: str, when: str, message: str = "did a thing",
                repo: str = "acme/app") -> Dict[str, object]:
    return {
        "sha": sha,
        "html_url": f"https://github.com/{repo}/commit/{sha}",
        "repository": {"full_name": repo},
        "commit": {"message": message, "author": {"date": when}},
    }


class FakeGh:
    """Serves search/commits from an in-memory list, honouring author-date ranges and paging."""

    def __init__(self, items: List[Dict[str, object]], login: str = "octocat",
                 reported_total: Optional[int] = None) -> None:
        self.items = items
        self.login = login
        self.reported_total = reported_total
        self.queries: List[str] = []

    def __call__(self, args: Sequence[str]) -> str:
        if list(args) == ["api", "user"]:
            return json.dumps({"login": self.login})
        params = dict(a.split("=", 1) for a in args if "=" in a)
        query, page, per_page = params["q"], int(params["page"]), int(params["per_page"])
        self.queries.append(query)
        match = re.search(r"author-date:(\S+)\.\.(\S+)", query)
        assert match, query
        low, high = match.groups()
        # GitHub's own interpretation is UTC-based; approximate it with the date prefix.
        hits = [i for i in self.items if low <= i["commit"]["author"]["date"][:10] <= high]
        total = self.reported_total if self.reported_total is not None else len(hits)
        page_items = hits[(page - 1) * per_page:page * per_page]
        return json.dumps({"total_count": total, "incomplete_results": False, "items": page_items})


def commit(sha: str, when: str, message: str = "did a thing", repo: str = "acme/app") -> Commit:
    return Commit.from_search_item(search_item(sha, when, message, repo))


class CommitTests(unittest.TestCase):
    def test_day_uses_author_local_date(self) -> None:
        c = commit("a" * 40, "2026-03-10T00:30:00.000+02:00")
        self.assertEqual(c.day, "2026-03-10")
        self.assertEqual(c.time, "00:30")

    def test_merge_title_is_pr_title(self) -> None:
        c = commit("a" * 40, "2026-03-10T10:00:00+02:00",
                   "Merge pull request #7 from acme/feat\n\nAdd login page")
        self.assertTrue(c.is_merge)
        self.assertEqual(c.merge_title, "Add login page")

    def test_non_merge_title_is_subject(self) -> None:
        c = commit("a" * 40, "2026-03-10T10:00:00+02:00", "fix bug\n\ndetails")
        self.assertFalse(c.is_merge)
        self.assertEqual(c.merge_title, "fix bug")

    def test_malformed_search_item_raises(self) -> None:
        with self.assertRaises(WorkLogError):
            Commit.from_search_item({"sha": "x"})

    def test_invalid_date_raises(self) -> None:
        with self.assertRaises(WorkLogError):
            Commit.from_search_item(search_item("a" * 40, "yesterday"))


class FetchTests(unittest.TestCase):
    def test_month_windows_split_on_month_boundaries(self) -> None:
        self.assertEqual(work_log.month_windows(date(2026, 1, 30), date(2026, 3, 2)), [
            (date(2026, 1, 30), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 3, 1), date(2026, 3, 2)),
        ])

    def test_fetch_paginates_filters_to_local_days_and_dedupes(self) -> None:
        items = [search_item(f"{i:040d}", f"2026-03-{10 + i % 5:02d}T10:00:00+02:00")
                 for i in range(250)]
        items.append(search_item("b" * 40, "2026-03-09T23:00:00+02:00"))  # day before range
        items.append(items[0])  # duplicate across windows
        gh = FakeGh(items)
        result = work_log.fetch_commits(gh, "octocat", None, date(2026, 3, 10), date(2026, 3, 14))
        self.assertEqual(len(result), 250)
        self.assertEqual(result, sorted(result, key=lambda c: c.date))
        self.assertTrue(all("2026-03-10" <= c.day <= "2026-03-14" for c in result))

    def test_window_over_search_cap_is_bisected(self) -> None:
        items = [search_item(f"{i:040d}", f"2026-03-{1 + i % 20:02d}T10:00:00+00:00")
                 for i in range(1200)]
        gh = FakeGh(items)
        result = work_log.fetch_window(gh, "octocat", None, date(2026, 3, 1), date(2026, 3, 20))
        self.assertEqual(len(result), 1200)
        self.assertGreater(len(set(gh.queries)), 1)

    def test_single_day_over_cap_raises(self) -> None:
        gh = FakeGh([], reported_total=1001)
        with self.assertRaisesRegex(WorkLogError, "search cap"):
            work_log.fetch_window(gh, "octocat", None, date(2026, 3, 1), date(2026, 3, 1))

    def test_count_mismatch_raises(self) -> None:
        gh = FakeGh([search_item("a" * 40, "2026-03-01T10:00:00+00:00")], reported_total=5)
        with self.assertRaisesRegex(WorkLogError, "reported 5 commits"):
            work_log.fetch_window(gh, "octocat", None, date(2026, 3, 1), date(2026, 3, 1))

    def test_owner_is_added_to_query(self) -> None:
        self.assertEqual(work_log.build_query("octocat", "acme", date(2026, 3, 1), date(2026, 3, 2)),
                         "author:octocat author-date:2026-03-01..2026-03-02 org:acme")

    def test_rate_limit_is_retried(self) -> None:
        calls: List[int] = []
        waits: List[float] = []

        def flaky(args: Sequence[str]) -> str:
            calls.append(1)
            if len(calls) < 3:
                raise WorkLogError("HTTP 403: API rate limit exceeded")
            return "ok"

        self.assertEqual(work_log.with_rate_limit_retry(flaky, waits.append)(["x"]), "ok")
        self.assertEqual(len(waits), 2)

    def test_other_gh_errors_are_not_retried(self) -> None:
        def broken(args: Sequence[str]) -> str:
            raise WorkLogError("HTTP 401: Bad credentials")

        with self.assertRaisesRegex(WorkLogError, "Bad credentials"):
            work_log.with_rate_limit_retry(broken, lambda _: self.fail("slept"))(["x"])


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commit_set = CommitSet("octocat", "acme", date(2026, 3, 9), date(2026, 3, 13), [
            commit("a" * 40, "2026-03-10T09:00:00+02:00", "add `login` | form"),
            commit("b" * 40, "2026-03-10T11:00:00+02:00", "Merge pull request #1 from acme/x\n\nLogin"),
        ])

    def test_render_includes_summary_commits_and_idle_weekdays(self) -> None:
        output = work_log.render(self.commit_set, {"2026-03-10": "Built the login form."})
        self.assertIn("## Tue 2026-03-10", output)
        self.assertIn("Built the login form.", output)
        self.assertIn("2 commits", output)
        self.assertIn(r"add \`login\` \| form", output)
        self.assertIn("2026-03-09, 2026-03-11, 2026-03-12, 2026-03-13", output)
        self.assertIn("`octocat` in `acme`", output)

    def test_render_rejects_missing_or_extra_summaries(self) -> None:
        with self.assertRaisesRegex(WorkLogError, "missing=\\['2026-03-10'\\]"):
            work_log.render(self.commit_set, {})
        with self.assertRaisesRegex(WorkLogError, "without commits=\\['2026-03-11'\\]"):
            work_log.render(self.commit_set, {"2026-03-10": "x", "2026-03-11": "y"})

    def test_digest_shows_pr_titles_for_merges(self) -> None:
        self.assertEqual(work_log.digest(self.commit_set.commits),
                         "## 2026-03-10\n[app]\n- add `login` | form\n- merged: Login")


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_commit_set_round_trips(self) -> None:
        original = CommitSet("octocat", None, date(2026, 3, 1), date(2026, 3, 31),
                             [commit("a" * 40, "2026-03-10T09:00:00+02:00")])
        path = self.tmp / "commits.json"
        work_log.save_commit_set(original, path)
        self.assertEqual(work_log.load_commit_set(path), original)

    def test_summaries_validation(self) -> None:
        path = self.tmp / "summaries.json"
        for bad in ('["x"]', '{"10.03.2026": "x"}', '{"2026-03-10": ""}', "not json"):
            path.write_text(bad)
            with self.subTest(bad=bad), self.assertRaises(WorkLogError):
                work_log.load_summaries(path)

    def test_missing_file_is_reported(self) -> None:
        with self.assertRaisesRegex(WorkLogError, "cannot read"):
            work_log.load_summaries(self.tmp / "nope.json")


class CliTests(unittest.TestCase):
    def test_fetch_then_render_end_to_end(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        gh = FakeGh([search_item("a" * 40, "2026-03-10T09:00:00+02:00", "add login")])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = work_log.main(["fetch", "2026-03-09", "2026-03-13",
                                  "--out", str(tmp / "c.json")], gh=gh)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("- add login", out.getvalue())
        self.assertIn("by octocat", err.getvalue())

        (tmp / "s.json").write_text(json.dumps({"2026-03-10": "Login work."}))
        with redirect_stdout(io.StringIO()):
            code = work_log.main(["render", "--commits", str(tmp / "c.json"),
                                  "--summaries", str(tmp / "s.json"), "--out", str(tmp / "log.md")])
        self.assertEqual(code, 0)
        self.assertIn("Login work.", (tmp / "log.md").read_text())

    def test_reversed_range_is_an_error(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            code = work_log.main(["fetch", "2026-03-13", "2026-03-09", "--out", "x"], gh=FakeGh([]))
        self.assertEqual(code, 1)
        self.assertIn("is after", err.getvalue())


if __name__ == "__main__":
    unittest.main()
