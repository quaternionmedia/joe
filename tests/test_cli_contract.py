"""`joe serve` and `joe check`: the performing family's demo contract.

Neither may run for real here -- `serve` binds two ports and `check` drives a
browser -- so what is held is what `serve` starts and in which order, and that a
check with nothing to check against says so rather than failing.
"""

from typer.testing import CliRunner

import cli

runner = CliRunner()


class Finished:
    """A process that has already exited, so `serve` stops waiting on it."""

    def __init__(self, argv, **kwargs):
        self.argv, self.kwargs, self.pid = argv, kwargs, 0

    def poll(self):
        return 0


def test_serve_starts_the_api_then_vite_on_the_ports_given(tmp_path, monkeypatch):
    vite = tmp_path / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text("")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "node")
    asked = []
    monkeypatch.setattr(cli, "_answers", lambda url, timeout=2.0: asked.append(url) or True)
    started = []
    monkeypatch.setattr(cli.subprocess, "Popen",
                        lambda argv, **kwargs: started.append(Finished(argv, **kwargs)) or started[-1])
    monkeypatch.setattr(cli, "_kill", lambda proc: None)

    result = runner.invoke(cli.app, [
        "serve", "--host", "127.0.0.1", "--port", "18430", "--api-port", "18431",
        "--qmcp-url", "http://127.0.0.1:18432", "--state", str(tmp_path / "state")])

    assert result.exit_code == 0, result.output
    api, web = started
    assert api.argv[1:] == ["-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "18431"]
    assert api.kwargs["cwd"] == tmp_path
    assert asked == ["http://127.0.0.1:18431/api/health"]  # Vite waits for the API
    assert web.argv == ["node", str(vite), "--host", "127.0.0.1", "--port", "18430", "--strictPort"]
    assert web.kwargs["env"]["JOE_API_URL"] == "http://127.0.0.1:18431"
    assert web.kwargs["env"]["QMCP_URL"] == "http://127.0.0.1:18432"
    assert (tmp_path / "state").is_dir()


def test_check_with_nothing_answering_cannot_say_rather_than_fail(tmp_path):
    # Port 9 is discard: nothing serves HTTP there, and nothing is bound here.
    result = runner.invoke(cli.app, [
        "check", "--url", "http://127.0.0.1:9/joe/", "--shots", str(tmp_path / "shots")])

    assert result.exit_code == cli.CANNOT_SAY == 3
    assert "nothing answers at http://127.0.0.1:9/joe/" in result.output
    assert not (tmp_path / "shots").exists()


def test_check_with_a_broken_pytest_cannot_say_rather_than_fail(tmp_path, monkeypatch):
    """`python -m` exits 1 for a missing module, which is a failed assertion's status."""
    monkeypatch.setattr(cli, "_answers", lambda url, timeout=2.0: True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)  # a page loading nothing from the network
    broken = cli.subprocess.CompletedProcess(
        [], 1, "", "No module named pytest.__main__; 'pytest' is a package")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: broken)

    result = runner.invoke(cli.app, [
        "check", "--url", "http://127.0.0.1:18430/joe/", "--shots", str(tmp_path / "shots")])

    assert result.exit_code == cli.CANNOT_SAY
    assert "pytest does not run here" in result.output
