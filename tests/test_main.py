import importlib
import os
import sys
from unittest.mock import patch

from Modules.utilities import make_directories


def _reload_main_with_patched_directory_discovery(fake_dirs):
    """Reload main.py after patching directory creation used at import time."""
    sys.modules.pop("main", None)
    with patch("Modules.utilities.make_directories", return_value=fake_dirs):
        import main

        return importlib.reload(main)


def test_audio_to_midi_initialization_uses_discovered_paths():
    fake_dirs = {
        "iter": "01-01-26_00-00-00",
        "iter_dir": r"C:\\tmp\\Data\\Output\\01-01-26_00-00-00\\",
        "audio_dir": r"C:\\tmp\\Data\\Audio\\",
        "chroma_dir": r"C:\\tmp\\Data\\Output\\01-01-26_00-00-00\\Chroma\\",
        "midi_dir": r"C:\\tmp\\Data\\Output\\01-01-26_00-00-00\\MIDI\\",
    }
    fake_audio_files = [
        r"C:\\tmp\\Data\\Audio\\test_audio_file1.wav",
        r"C:\\tmp\\Data\\Audio\\test_audio_file2.mp3",
    ]

    with patch("Modules.utilities.get_audio_files", return_value=fake_audio_files), patch(
        "Modules.utilities.save_json"
    ) as save_json_mock:
        main = _reload_main_with_patched_directory_discovery(fake_dirs)

        with patch("main.Audio") as audio_mock:
            audio_to_midi = main.AudioToMidi()

    assert len(audio_to_midi.audio) == 2
    audio_mock.assert_any_call(
        "test_audio_file1",
        fake_audio_files[0],
        fake_dirs["iter_dir"],
        fake_dirs["chroma_dir"],
        fake_dirs["midi_dir"],
        audio_to_midi.overtone_weights,
        audio_to_midi.chroma_threshold,
        audio_to_midi.min_duration,
        audio_to_midi.harmonic_threshold,
    )
    audio_mock.assert_any_call(
        "test_audio_file2",
        fake_audio_files[1],
        fake_dirs["iter_dir"],
        fake_dirs["chroma_dir"],
        fake_dirs["midi_dir"],
        audio_to_midi.overtone_weights,
        audio_to_midi.chroma_threshold,
        audio_to_midi.min_duration,
        audio_to_midi.harmonic_threshold,
    )
    save_json_mock.assert_called_once()


def test_make_directories_creates_expected_structure(tmp_path):
    base = str(tmp_path)
    os.makedirs(os.path.join(base, "Data", "Audio"), exist_ok=True)

    directories = make_directories(base)

    assert directories["audio_dir"].endswith("Data\\Audio\\")
    assert os.path.isdir(directories["audio_dir"])
    assert os.path.isdir(directories["iter_dir"])
    assert os.path.isdir(directories["midi_dir"])
    assert os.path.isdir(directories["chroma_dir"])
