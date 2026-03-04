import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from Modules.utilities import get_audio_files, make_directories, save_json


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


def test_make_directories_returns_all_expected_keys(tmp_path):
    base = str(tmp_path)
    os.makedirs(os.path.join(base, "Data", "Audio"), exist_ok=True)

    directories = make_directories(base)

    assert set(directories.keys()) == {"iter", "iter_dir", "audio_dir", "chroma_dir", "midi_dir"}


def test_get_audio_files_returns_all_audio_files(tmp_path):
    audio_dir = tmp_path / "Audio"
    audio_dir.mkdir()
    (audio_dir / "track1.wav").write_bytes(b"")
    (audio_dir / "track2.mp3").write_bytes(b"")

    files = get_audio_files(str(audio_dir) + "\\")

    assert len(files) == 2
    assert any("track1.wav" in f for f in files)
    assert any("track2.mp3" in f for f in files)


def test_get_audio_files_just_one_file_flag(tmp_path):
    audio_dir = tmp_path / "Audio"
    audio_dir.mkdir()
    (audio_dir / "a.wav").write_bytes(b"")
    (audio_dir / "b.wav").write_bytes(b"")

    files = get_audio_files(str(audio_dir) + "\\", just_one_file=True)

    assert len(files) == 1


def test_get_audio_files_missing_dir_exits():
    with pytest.raises(SystemExit):
        get_audio_files("/nonexistent/path/Audio\\")


def test_get_audio_files_empty_dir_exits(tmp_path):
    audio_dir = tmp_path / "Audio"
    audio_dir.mkdir()

    with pytest.raises(SystemExit):
        get_audio_files(str(audio_dir) + "\\")


def test_save_json_writes_parseable_file(tmp_path):
    iteration = "01-01-26_00-00-00"
    iteration_dir = str(tmp_path) + "\\"

    note_mock = MagicMock()
    note_mock.note = "C4"
    note_mock.pitch = 60
    note_mock.start_dur = [(0.0, 0.5)]

    chroma_mock = MagicMock()
    chroma_mock.file_path = "chroma.png"
    chroma_mock.midi.file_path = "output.mid"
    chroma_mock.midi.notes = [note_mock]

    audio_mock = MagicMock()
    audio_mock.name = "test_track"
    audio_mock.file_path = "Data/Audio/test_track.wav"
    audio_mock.sr = 22050
    audio_mock.full_chroma_path = "chroma_full.png"
    audio_mock.chromas = {"cqt": chroma_mock}

    save_json(
        iteration=iteration,
        iteration_dir=iteration_dir,
        min_duration=0.1,
        fft_sizes=[512, 1024],
        chroma_threshold=0.3,
        harmonic_threshold=0.3,
        overtone_weights=[0.5, 0.4],
        audio_files=["Data/Audio/test_track.wav"],
        audios=[audio_mock],
    )

    output_file = tmp_path / f"Process_Data_{iteration}.json"
    assert output_file.exists()
    with open(output_file) as f:
        data = json.load(f)

    assert data["iteration"] == iteration
    assert "audio" in data
    assert "test_track" in data["audio"]
    assert data["audio"]["test_track"]["sr"] == 22050
