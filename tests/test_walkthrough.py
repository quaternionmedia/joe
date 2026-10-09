"""The walkthrough's own properties, per the one-executable-walkthrough record.

These are about the page set rather than the pages' contents: the contents are
checked by running them, which is the point of the form. What running them
cannot check is whether the set is well formed, whether a page declares the
runtime it needs, whether every page is wired into CI, and whether the media
a page shows is media a page produced.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALKTHROUGH = ROOT / "walkthrough"
MEDIA = WALKTHROUGH / "media"

# `NN-<slug>.md`, ordinal first, ordered by filename.
PAGE_NAME = re.compile(r"^(\d{2})-[a-z0-9-]+\.md$")

HERMETIC, BOUND = "Runtime: hermetic", "Runtime-bound"

# The command that runs everything, spelled once here and checked for in every
# surface that tells a reader how to run the checks.
COMMAND = "uv run pytest tests walkthrough --doctest-glob=*.md"


def pages() -> list[Path]:
    return sorted(WALKTHROUGH.glob("*.md"))


def opening(page: Path) -> str:
    return "\n".join(page.read_text(encoding="utf-8").splitlines()[:4])


def bound(page: Path) -> bool:
    return BOUND in opening(page)


class PageSetTests(unittest.TestCase):
    def test_there_is_a_walkthrough(self):
        self.assertTrue(pages(), "a walkthrough with no pages is not one")

    def test_every_page_is_named_for_its_place_in_the_order(self):
        for page in pages():
            with self.subTest(page.name):
                self.assertRegex(page.name, PAGE_NAME)

    def test_the_ordinals_run_from_one_with_no_gaps_and_no_repeats(self):
        ordinals = [int(PAGE_NAME.match(p.name).group(1)) for p in pages()]
        self.assertEqual(ordinals, list(range(1, len(ordinals) + 1)))

    def test_every_page_declares_its_runtime_in_its_opening_lines(self):
        for page in pages():
            with self.subTest(page.name):
                head = opening(page)
                self.assertTrue(HERMETIC in head or BOUND in head,
                                f"{page.name} does not say what it needs to run")
                self.assertFalse(HERMETIC in head and BOUND in head)

    def test_hermetic_pages_come_first(self):
        # A runtime-bound page early in the order makes the whole set need a
        # browser before a newcomer has built anything.
        seen_bound = False
        for page in pages():
            if bound(page):
                seen_bound = True
            elif seen_bound:
                self.fail(f"{page.name} is hermetic and sits after a bound page")

    def test_onboarding_and_cookbook_are_separate_pages(self):
        names = [p.name for p in pages()]
        self.assertEqual(names[0], "01-onboarding.md")
        self.assertTrue(any(n.endswith("-cookbook.md") for n in names))

    def test_no_page_skips(self):
        # A skip is not a pass. A page that vanishes into a skip count reports
        # green for a demonstration nobody ran.
        for page in pages():
            body = page.read_text(encoding="utf-8")
            with self.subTest(page.name):
                for skip in ("pytest.skip", "SkipTest", "skipUnless", "+SKIP"):
                    self.assertNotIn(skip, body)

    def test_this_file_does_not_skip_either(self):
        body = Path(__file__).read_text(encoding="utf-8")
        body = re.sub(r"#.*$", "", body, flags=re.M)
        body = re.sub(r'""".*?"""', "", body, flags=re.S)
        self.assertNotIn("self." + "skipTest(", body)

    def test_an_absent_runtime_is_raised_rather_than_skipped(self):
        support = (WALKTHROUGH / "support.py").read_text(encoding="utf-8")
        self.assertIn("class Unreachable(RuntimeError)", support)
        self.assertNotIn("pytest.skip", support)


class ExampleDisciplineTests(unittest.TestCase):
    """An example may not discard a failure.

    doctest passes an example that raises nothing and declares no output, so
    `subprocess.run([...])` against a command exiting non-zero passes. Every
    example that runs a process carries `check=True` or shows its returncode.
    """

    def test_no_example_runs_a_process_without_checking_it(self):
        for page in pages():
            lines = page.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines):
                if "subprocess.run" not in line or not line.lstrip().startswith(">>>"):
                    continue
                # An example may continue on `...` lines; read all of it.
                example = line
                for following in lines[number + 1:]:
                    if not following.lstrip().startswith("..."):
                        break
                    example += following
                with self.subTest(f"{page.name}:{number + 1}"):
                    self.assertTrue("check=True" in example or "returncode" in example,
                                    "an example that runs a process discards its failure")


class MediaTests(unittest.TestCase):
    """Recorded, never compared, and never orphaned.

    The pictures are byproducts of the run that asserted the behaviour. What
    is checkable here is the joint between a page and a file: a page showing
    an image nothing takes is stale documentation, and a file no page shows
    is a leftover.
    """

    REGENERATE = "uv run pytest walkthrough/03-in-the-browser.md --doctest-glob=*.md"

    @staticmethod
    def shown() -> set[str]:
        found = set()
        for page in pages():
            found |= set(re.findall(r"!\[[^\]]*\]\(media/([^)]+)\)",
                                    page.read_text(encoding="utf-8")))
        return found

    @staticmethod
    def taken() -> set[str]:
        """The files the pages operate the shutter for, read off the calls.

        Not off the directory: the directory is the output, and reading the
        output to check the generator is how a generator that stopped running
        goes unnoticed.
        """
        found = set()
        for page in pages():
            body = page.read_text(encoding="utf-8")
            slugs = re.findall(r"Shots\(\s*['\"]([^'\"]+)['\"]\s*\)", body)
            for name in re.findall(r"shots\.take\(\s*\w+\s*,\s*['\"]([^'\"]+)['\"]", body):
                found.add(f"{slugs[0]}-{name}.png")
        return found

    def test_the_media_is_in_the_checkout(self):
        self.assertTrue(MEDIA.is_dir(), f"walkthrough/media is missing: {self.REGENERATE}")

    def test_every_image_a_page_shows_is_one_a_page_takes(self):
        shown, taken = self.shown(), self.taken()
        self.assertTrue(taken, "no page takes a screenshot at all")
        self.assertEqual(sorted(shown - taken), [], "shown, and taken by no page")
        self.assertEqual(sorted(taken - shown), [], "taken, and shown by no page")

    def test_every_image_a_page_shows_exists(self):
        for name in self.shown():
            with self.subTest(name):
                self.assertTrue((MEDIA / name).is_file(),
                                f"a page shows {name} and nothing recorded it: {self.REGENERATE}")

    def test_every_recorded_image_is_shown_by_a_page(self):
        shown = self.shown()
        for path in MEDIA.glob("*.png"):
            with self.subTest(path.name):
                self.assertIn(path.name, shown, "recorded, and shown by no page")

    def test_the_readme_shows_a_screen_the_walkthrough_recorded(self):
        # The homepage picture is the walkthrough's, so it changes when the
        # screen does instead of showing the day somebody last remembered.
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        shown = re.findall(r"!\[[^\]]*\]\(walkthrough/media/([^)]+)\)", readme)
        self.assertTrue(shown, "the README shows no recorded screen")
        for name in shown:
            with self.subTest(name):
                self.assertIn(name, self.shown())

    def test_the_recorder_never_compares(self):
        # A test that diffs images fails on a font and gets switched off,
        # taking the assertions beside it.
        source = (WALKTHROUGH / "support.py").read_text(encoding="utf-8")
        source = re.sub(r'""".*?"""', "", source, flags=re.S)
        for comparison in ("assert_snapshot", "to_match_snapshot", "toHaveScreenshot",
                           "image_diff", "compare_images", "baseline"):
            with self.subTest(comparison):
                self.assertNotIn(comparison, source)

    def test_nothing_un_ignores_the_media_by_hand(self):
        # Media is tracked like any other file, so there is no hand-written
        # negation list to fall out of step with the pages.
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("walkthrough", ignore)


class WiringTests(unittest.TestCase):
    """The pages run where somebody looks, under the command people run."""

    def test_no_testpaths(self):
        # `testpaths` is ignored the moment pytest is handed a path, so a
        # walkthrough wired that way is collected by nobody.
        config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        settings = "\n".join(line for line in config.splitlines()
                             if not line.lstrip().startswith("#"))
        self.assertNotRegex(settings, r"(?m)^\s*testpaths\s*=")

    def test_every_surface_spells_the_command(self):
        for surface in ("README.md", "docs/contributing.md",
                        "walkthrough/01-onboarding.md", "walkthrough/02-cookbook.md"):
            with self.subTest(surface):
                self.assertIn(COMMAND, (ROOT / surface).read_text(encoding="utf-8"))

    def test_ci_runs_every_page_in_the_job_for_its_tier(self):
        # Hermetic pages run beside the suite on every platform; a bound page
        # runs in the job that provisions its browser. A page added and wired
        # into neither would be green here and run nowhere.
        tests = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        e2e = (ROOT / ".github/workflows/e2e.yml").read_text(encoding="utf-8")
        for page in pages():
            with self.subTest(page.name):
                job = e2e if bound(page) else tests
                self.assertIn(f"walkthrough/{page.name}", job)
        for flow in (tests, e2e):
            self.assertIn("--doctest-glob=*.md", flow)

    def test_the_bound_job_keeps_what_it_drew(self):
        e2e = (ROOT / ".github/workflows/e2e.yml").read_text(encoding="utf-8")
        self.assertIn("upload-artifact", e2e)
        self.assertIn("walkthrough/media", e2e)

    def test_pytest_collects_every_page(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "walkthrough", "--doctest-glob=*.md",
             "--collect-only", "-q", "-p", "no:cacheprovider"],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        collected = [line for line in result.stdout.splitlines()
                     if re.match(r"walkthrough[\\/]\d{2}-", line)]
        self.assertEqual(len(collected), len(pages()), result.stdout)


class ContributingTests(unittest.TestCase):
    """Onboarding lives in one place, and it is the page that runs."""

    def test_the_guide_points_at_the_onboarding_page_and_the_manual_plan(self):
        body = (ROOT / "docs/contributing.md").read_text(encoding="utf-8")
        self.assertIn("walkthrough/01-onboarding.md", body)
        self.assertIn("docs/manual-test-plan.md", body)

    def test_the_guide_says_to_commit_redrawn_pictures(self):
        body = (ROOT / "docs/contributing.md").read_text(encoding="utf-8")
        self.assertIn("walkthrough/media", body)
        self.assertRegex(body, r"(?is)commit\b.{0,80}\bpictures?\b")
