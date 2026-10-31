"""`joe backend` serves the API on 1059, its port in qm's allocation."""

from unittest.mock import patch

from typer.testing import CliRunner

import cli

runner = CliRunner()


def test_backend_serves_on_1059():
    with patch("cli.subprocess.run") as run:
        result = runner.invoke(cli.app, ["backend"])

    assert result.exit_code == 0
    args = run.call_args.args[0]
    assert args[args.index("--port") + 1] == "1059"
