"""What joe needs of the machine's audio server, and what it does not.

Importing sounddevice starts PortAudio, and PortAudio fails to start where no
audio server runs: on a hosted Linux runner, `libportaudio2` brings
PulseAudio's client and no PulseAudio server answers it. The API loads there
all the same, and every other test replaces sounddevice. Opening the
machine's own audio is the `local` check, run on a person's machine; the
hosted runners deselect it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# sounddevice as it imports with no audio server: PortAudio refuses to start.
NO_AUDIO_SERVER = textwrap.dedent("""
    import sys

    class NoAudioServer:
        def find_spec(self, name, path=None, target=None):
            if name == "sounddevice":
                raise OSError("Error initializing PortAudio: PulseAudio_Initialize: "
                              "Can't connect to server")
            return None

    sys.meta_path.insert(0, NoAudioServer())
""")


def test_the_api_loads_on_a_machine_with_no_audio_server():
    loaded = subprocess.run([sys.executable, "-c", NO_AUDIO_SERVER + "import api\n"],
                            cwd=ROOT, capture_output=True, text=True)
    assert loaded.returncode == 0, loaded.stderr


def test_the_stand_in_refuses_sounddevice_as_a_machine_with_no_audio_server_does():
    refused = subprocess.run([sys.executable, "-c", NO_AUDIO_SERVER + "import sounddevice\n"],
                             cwd=ROOT, capture_output=True, text=True)
    assert refused.returncode != 0
    assert "Error initializing PortAudio" in refused.stderr


@pytest.mark.local
def test_portaudio_starts_and_lists_this_machines_audio():
    import sounddevice as sd

    assert sd.query_hostapis(), "PortAudio started and found no host API"
    assert sd.query_devices(), "PortAudio started and found no device"
