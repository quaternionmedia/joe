import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from Modules.utilities import make_directories, save_json


def _reload_main_with_patched_directory_discovery(fake_dirs):
    """Reload main.py after patching directory creation used at import time."""
    sys.modules.pop("main", None)
    with patch("Modules.utilities.make_directories", return_value=fake_dirs):
        import main

        return importlib.reload(main)


def test_audio_to_midi_initialization_uses_discovered_paths():
    # Built with the host's own separator: main.py derives each name with
    # os.path.basename, which cannot split a foreign separator's paths.
    base = os.path.join(os.sep, "tmp", "Data")
    out = os.path.join(base, "Output", "01-01-26_00-00-00")
    fake_dirs = {
        "iter": "01-01-26_00-00-00",
        "iter_dir": out + os.sep,
        "audio_dir": os.path.join(base, "Audio") + os.sep,
        "chroma_dir": os.path.join(out, "Chroma") + os.sep,
        "midi_dir": os.path.join(out, "MIDI") + os.sep,
    }
    fake_audio_files = [
        os.path.join(base, "Audio", "test_audio_file1.wav"),
        os.path.join(base, "Audio", "test_audio_file2.mp3"),
    ]

    with patch("Modules.utilities.save_json") as save_json_mock:
        main = _reload_main_with_patched_directory_discovery(fake_dirs)

        with patch("main.Audio") as audio_mock:
            audio_to_midi = main.AudioToMidi(fake_audio_files)
    sys.modules.pop("main", None)

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

    assert directories["audio_dir"].endswith(os.path.join("Data", "Audio") + os.sep)
    assert os.path.isdir(directories["audio_dir"])
    assert os.path.isdir(directories["iter_dir"])
    assert os.path.isdir(directories["midi_dir"])
    assert os.path.isdir(directories["chroma_dir"])


def test_make_directories_returns_all_expected_keys(tmp_path):
    base = str(tmp_path)
    os.makedirs(os.path.join(base, "Data", "Audio"), exist_ok=True)

    directories = make_directories(base)

    assert set(directories.keys()) == {"iter", "iter_dir", "audio_dir", "chroma_dir", "midi_dir"}


def _main_over(audio_dir):
    """main.py, imported with its folders under `audio_dir`'s parent."""
    out = os.path.join(str(audio_dir.parent), "Output", "01-01-26_00-00-00")
    return _reload_main_with_patched_directory_discovery({
        "iter": "01-01-26_00-00-00", "iter_dir": out + os.sep, "audio_dir": str(audio_dir) + os.sep,
        "chroma_dir": os.path.join(out, "Chroma") + os.sep, "midi_dir": os.path.join(out, "MIDI") + os.sep,
    })


@pytest.fixture
def recordings(tmp_path):
    audio_dir = tmp_path / "Audio"
    audio_dir.mkdir()
    for i, name in enumerate(["b.wav", "a.wav"]):
        (audio_dir / name).write_bytes(b"RIFF")
        os.utime(audio_dir / name, (1_000_000 + i, 1_000_000 + i))
    yield audio_dir
    sys.modules.pop("main", None)


@pytest.mark.parametrize("argv, chosen", [([], ["a.wav"]), (["--all"], ["a.wav", "b.wav"]), (["b.wav"], ["b.wav"])])
def test_main_py_analyses_the_newest_those_named_or_all(recordings, argv, chosen):
    main = _main_over(recordings)
    assert [os.path.basename(f) for f in main.chosen_files(argv)] == chosen


@pytest.mark.parametrize("argv", [["--all", "a.wav"], ["absent.wav"]])
def test_main_py_refuses_names_with_all_and_a_name_that_is_no_recording(recordings, argv):
    main = _main_over(recordings)
    with pytest.raises(SystemExit) as stopped:
        main.chosen_files(argv)
    assert stopped.value.code == 2


def test_main_py_with_nothing_to_analyse_says_so_and_stops(tmp_path, capsys):
    (tmp_path / "Audio").mkdir()
    main = _main_over(tmp_path / "Audio")
    try:
        with pytest.raises(SystemExit) as stopped:
            main.chosen_files([])
    finally:
        sys.modules.pop("main", None)
    assert stopped.value.code == 0
    assert "No audio files found" in capsys.readouterr().out
