"""The suite is the same on every machine: no setting of joe's in the shell, and no
microphone saved in the checkout, reaches a test, and the code under test is this
checkout's."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# joe's settings, set as a person's shell or a launcher might hold them.
MACHINE = {
    "JOE_AUDIO_FILE": "nowhere.wav",
    "JOE_BARGE_FACTOR": "9",
    "JOE_BARGE_IN": "0",
    "JOE_DATAPOINTS": "0",
    "JOE_INPUT_DEVICE": "Q8n",
    "JOE_LANGUAGE": "de",
    "JOE_OUTPUT_DEVICE": "Speakers",
    "VOX_OUTPUT_DEVICE": "Speakers",
}
INNER = "JOE_SUITE_UNDER_MACHINE_SETTINGS"


def test_the_code_under_test_is_this_checkout_s():
    import api
    from Modules import Voice

    assert Path(api.__file__).resolve().parent == ROOT
    assert Path(Voice.__file__).resolve().parents[1] == ROOT


def test_the_saved_microphone_is_the_test_s_own():
    from Modules import Voice

    assert not Voice.SAVED_DEVICE.resolve().is_relative_to(ROOT / "Data")


@pytest.mark.skipif(os.environ.get(INNER) == "1", reason="the run this test starts")
def test_the_voice_tests_pass_with_the_machine_s_settings_set():
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_voice.py", "tests/test_transcript.py", "tests/test_control.py",
         "tests/test_watch.py", "tests/test_cli_voice_devices.py", "tests/test_conversation.py"],
        cwd=ROOT, env={**os.environ, **MACHINE, INNER: "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert run.returncode == 0, run.stdout[-3000:]
