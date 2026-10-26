"""/api/media/{id}/transcribe and /api/media/capabilities.

By default whisper is a stand-in that answers as whisper does -- numpy floats,
words with their leading spaces -- and records what it was asked. One test
runs the real base model, from this machine's cache only, on a sentence the
platform's own speech engine says; it skips when either is missing.
"""

import os
import re
import string
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api
from Modules import Analysis, Media
from Modules.Voice import Voice
from tests.media_fixtures import ffmpeg_or_skip, synthesize_speech, tone, write_wav


class FakeWhisper:
    """whisper's model, answering one segment of two words, as whisper types it."""

    def __init__(self, delay: float = 0.0):
        self.device = SimpleNamespace(type="cpu")
        self.calls = []
        self.delay = delay
        self.active = 0
        self.most_at_once = 0
        self._lock = threading.Lock()

    def transcribe(self, audio, **options):
        with self._lock:
            self.active += 1
            self.most_at_once = max(self.most_at_once, self.active)
        time.sleep(self.delay)
        self.calls.append((audio, options))
        with self._lock:
            self.active -= 1
        words = [
            {"word": " Hello", "start": np.float64(0.12), "end": np.float64(0.5), "probability": np.float64(0.91234)},
            {"word": " there.", "start": np.float64(0.5), "end": np.float64(1.0004), "probability": np.float64(0.87)},
        ]
        return {
            "text": " Hello there.",
            "language": options.get("language") or "en",
            "segments": [{
                "id": 0, "seek": 0, "start": np.float64(0.0), "end": np.float64(1.24), "text": " Hello there.",
                "avg_logprob": -0.25, "no_speech_prob": 0.01, "compression_ratio": 0.8,
                **({"words": words} if options.get("word_timestamps") else {}),
            }],
        }


@pytest.fixture
def client():
    return TestClient(api.app)


@pytest.fixture
def fake(monkeypatch):
    model = FakeWhisper()
    loaded = []
    monkeypatch.setattr(Media.MediaSpeech, "_load_model",
                        classmethod(lambda cls, size: loaded.append(size) or model))
    model.loaded = loaded
    return model


@pytest.fixture
def two_seconds(client, tmp_path):
    ffmpeg_or_skip()
    path = write_wav(tmp_path / "tone.wav", tone(2, 44100), 44100)
    res = client.post("/api/media", content=path.read_bytes(), headers={"Content-Type": "audio/wav"})
    assert res.status_code == 201, res.text
    return res.json()["media_id"]


def detail(res, status: int) -> str:
    assert res.status_code == status, res.text
    assert set(res.json()) == {"detail"} and isinstance(res.json()["detail"], str)
    return res.json()["detail"]


# ─── With a stand-in ──────────────────────────────────────────────────────────

def test_a_transcript_has_segment_and_word_times_in_v1_s_shape(client, fake, two_seconds):
    res = client.post(f"/api/media/{two_seconds}/transcribe")

    assert res.status_code == 200, res.text
    assert res.json() == {
        "text": "Hello there.",
        "language": "en",
        "segments": [{
            "start": 0.0, "end": 1.24, "text": "Hello there.",
            "words": [
                {"start": 0.12, "end": 0.5, "word": " Hello", "probability": 0.9123},
                {"start": 0.5, "end": 1.0, "word": " there.", "probability": 0.87},
            ],
        }],
        "info": {"model": "whisper-base", "language": None, "words": True, "duration": 2.0,
                 "avg_logprob": -0.25, "no_speech_prob": 0.01, "compression_ratio": 0.8},
    }
    (audio, options), = fake.calls
    # whisper hears the 16 kHz mono copy, all of it, and detects the language.
    assert audio.dtype == np.float32 and audio.ndim == 1 and len(audio) == 32000
    assert options == {"word_timestamps": True, "fp16": False, "verbose": None}
    assert fake.loaded == ["base"]


@pytest.mark.parametrize("given, code", [("en", "en"), ("English", "en"), (" de ", "de"), ("japanese", "ja")])
def test_a_language_given_is_handed_to_whisper_as_its_code(client, fake, two_seconds, given, code):
    body = client.post(f"/api/media/{two_seconds}/transcribe", params={"language": given}).json()

    assert fake.calls[0][1]["language"] == code
    assert body["language"] == code and body["info"]["language"] == code


def test_an_empty_language_leaves_whisper_to_detect_it(client, fake, two_seconds):
    res = client.post(f"/api/media/{two_seconds}/transcribe?language=&words=true")

    assert res.status_code == 200, res.text
    assert "language" not in fake.calls[0][1]


def test_words_false_asks_whisper_for_none_and_answers_none(client, fake, two_seconds):
    body = client.post(f"/api/media/{two_seconds}/transcribe", params={"words": "false"}).json()

    assert fake.calls[0][1]["word_timestamps"] is False
    assert body["segments"][0]["words"] == [] and body["info"]["words"] is False


def test_an_unknown_language_is_422_and_whisper_is_not_run(client, fake, two_seconds):
    said = detail(client.post(f"/api/media/{two_seconds}/transcribe", params={"language": "klingon"}), 422)

    assert "unknown language 'klingon'" in said
    assert fake.calls == [] and fake.loaded == []


def test_words_must_be_true_or_false(client, fake):
    said = detail(client.post(f"/api/media/{'0' * 32}/transcribe", params={"words": "maybe"}), 422)

    assert said.startswith("words: ")


def test_an_upload_that_is_not_here_is_404(client, fake):
    assert "no such media" in detail(client.post(f"/api/media/{'0' * 32}/transcribe"), 404)
    assert fake.calls == []


def test_media_transcriptions_take_turns_on_one_model(client, two_seconds, monkeypatch):
    model = FakeWhisper(delay=0.2)
    monkeypatch.setattr(Media.MediaSpeech, "_load_model", classmethod(lambda cls, size: model))
    answers = []

    def ask():
        answers.append(client.post(f"/api/media/{two_seconds}/transcribe").status_code)

    threads = [threading.Thread(target=ask) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert answers == [200, 200, 200]
    assert model.most_at_once == 1


def test_a_transcription_runs_on_media_s_own_thread(client, two_seconds, monkeypatch):
    """Not on the pool FastAPI answers the voice API's routes with, so captions
    queued behind each other never keep a conversation waiting. Mutation: run
    it with `run_in_threadpool` -- red."""
    model = FakeWhisper()
    ran_on = []
    original = model.transcribe
    model.transcribe = lambda audio, **o: ran_on.append(threading.current_thread().name) or original(audio, **o)
    monkeypatch.setattr(Media.MediaSpeech, "_load_model", classmethod(lambda cls, size: model))

    assert client.post(f"/api/media/{two_seconds}/transcribe").status_code == 200

    assert ran_on and ran_on[0].startswith("joe-media-speech")


def test_media_has_a_whisper_of_its_own_and_never_the_voice_loop_s(client, two_seconds, monkeypatch):
    """Two decodes on one whisper model corrupt each other, so the voice loop's
    model -- loaded already, of the same size -- is not reused. Mutation: drop
    MediaSpeech's own `_model` -- it reads Voice's, red."""
    import sys

    voice_model = FakeWhisper()
    media_model = FakeWhisper()
    monkeypatch.setattr(Voice, "_model", voice_model)
    monkeypatch.setattr(Voice, "_model_size", "base")
    # A clean slate for media's own cache -- where it has one. Without it,
    # MediaSpeech reads Voice's, which is what this test is for.
    for name in ("_model", "_model_size"):
        if name in vars(Media.MediaSpeech):
            monkeypatch.setattr(Media.MediaSpeech, name, None)
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=lambda size: media_model))

    assert client.post(f"/api/media/{two_seconds}/transcribe").status_code == 200

    assert media_model.calls and not voice_model.calls
    assert Voice._model is voice_model and Media.MediaSpeech._model is media_model


# ─── What the engine says it can do ───────────────────────────────────────────

def test_the_capabilities_name_the_formats_features_and_model(client, monkeypatch):
    monkeypatch.setenv("JOE_FFMPEG", __file__)  # any file: only its presence is asked

    body = client.get("/api/media/capabilities").json()

    assert body == {
        "formats": sorted(Media.FORMATS),
        "features": ["tempo", "beats", "onsets", "loudness", "silence", "peaks"],
        "speech_model": "whisper-base",
        "word_timestamps": True,
        "max_bytes": 1024**3,
        "max_seconds": 7200.0,
        "ttl_seconds": 3600.0,
    }
    assert body["features"] == list(Analysis.FEATURES)


def test_without_ffmpeg_the_capabilities_take_no_format(client, tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_FFMPEG", str(tmp_path / "no-ffmpeg-here.exe"))

    assert client.get("/api/media/capabilities").json()["formats"] == []


def test_the_limits_in_the_capabilities_are_the_settings(client, monkeypatch):
    monkeypatch.setenv("JOE_MEDIA_MAX_BYTES", "5000000")
    monkeypatch.setenv("JOE_MEDIA_MAX_SECONDS", "90")

    body = client.get("/api/media/capabilities").json()

    assert (body["max_bytes"], body["max_seconds"]) == (5000000, 90.0)


# ─── The real model ───────────────────────────────────────────────────────────

def _cached_model(size: str) -> Path | None:
    """whisper's own cache path for `size`, if the model is already there."""
    root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"
    path = root / f"{size}.pt"
    return path if path.is_file() else None


@pytest.mark.whisper_model
def test_the_real_model_hears_a_spoken_sentence_with_its_words_in_order(client, tmp_path):
    if _cached_model(Media.speech_model_size()) is None:
        pytest.skip(f"the whisper {Media.speech_model_size()} model is not cached here; nothing is downloaded")
    ffmpeg_or_skip()
    sentence = "The quick brown fox jumps over the lazy dog."
    speech = synthesize_speech(sentence, tmp_path / "speech.wav")
    media_id = client.post("/api/media", content=speech.read_bytes(),
                           headers={"Content-Type": "audio/wav"}).json()["media_id"]

    res = client.post(f"/api/media/{media_id}/transcribe")

    assert res.status_code == 200, res.text
    body = res.json()

    def plain(text):
        return re.sub(f"[{re.escape(string.punctuation)}]", "", text).lower().split()

    assert body["language"] == "en"  # detected: none was given
    assert plain(body["text"]) == plain(sentence)
    words = [w for segment in body["segments"] for w in segment["words"]]
    assert [w for word in words for w in plain(word["word"])] == plain(sentence)
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)
    duration = client.post(f"/api/media/{media_id}/analyze", params={"features": "peaks"}).json()["duration"]
    assert all(0 <= w["start"] <= w["end"] <= duration + 0.05 for w in words)
    assert all(0 <= w["probability"] <= 1 for w in words)
    for segment in body["segments"]:
        assert "".join(w["word"] for w in segment["words"]).strip() == segment["text"]
