"""What the GitHub workflows may do: publish only from main, and write only
where they publish.

`deploy.yml` published the page on every event it ran on, PRs among them, so
a PR from a branch of this repository put its build on GitHub Pages before it
was merged, with a token that could write to the repository while it ran the
project's npm scripts.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    # YAML 1.1 reads a bare `on` as true.
    return workflow.get("on", workflow.get(True))


def test_the_page_is_published_only_from_main():
    deploy = load("deploy.yml")
    jobs = deploy["jobs"]
    publishing = [name for name, job in jobs.items()
                  if any("github-pages-deploy-action" in step.get("uses", "") for step in job["steps"])]

    assert publishing == ["deploy"]
    assert jobs["deploy"]["if"] == ("github.ref == 'refs/heads/main' && (github.event_name == 'push' "
                                    "|| github.event_name == 'workflow_dispatch')")
    assert jobs["deploy"]["needs"] == "build"


def test_a_pr_is_still_built():
    deploy = load("deploy.yml")

    assert triggers(deploy)["pull_request"] == {"branches": ["main"]}
    assert "if" not in deploy["jobs"]["build"]


def test_only_the_publish_can_write():
    deploy = load("deploy.yml")

    assert deploy["permissions"] == {"contents": "read"}
    assert "permissions" not in deploy["jobs"]["build"]
    assert deploy["jobs"]["deploy"]["permissions"] == {"contents": "write"}
    checkout = deploy["jobs"]["build"]["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


@pytest.mark.parametrize("name", ["tests.yml", "e2e.yml"])
def test_the_checks_run_with_a_read_only_token(name):
    workflow = load(name)

    assert workflow["permissions"] == {"contents": "read"}
    assert not any("permissions" in job for job in workflow["jobs"].values())
