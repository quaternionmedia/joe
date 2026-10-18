"""/api/media over HTTP: what is taken, what is refused and how, how long an
upload is kept, and analysis by id.

Every failure here is answered as `{"detail": str}`. The uploads are made at
test time by the ffmpeg joe runs (`tests/media_fixtures.py`); without one the
tests that upload skip, and the refusals that need no decoding still run.
"""

import re
import sys
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api
from Modules import Analysis, Media
from Modules.Media import MediaStore
from tests.media_fixtures import (
    KINDS, click_track, ffmpeg_make, ffmpeg_or_skip, make_kind, silence_tone_silence,
    video_with_late_audio, video_without_audio, write_wav,
)

HEX32 = re.compile(r"[0-9a-f]{32}")


@pytest.fixture
def client():
    return TestClient(api.app)


@pytest.fixture(scope="session")
def made(tmp_path_factory):
    """Where the ffmpeg-made uploads are kept for the session."""
    return tmp_path_factory.mktemp("media-fixtures")


@pytest.fixture
def ffmpeg():
    return ffmpeg_or_skip()


def post(client, data: bytes, content_type: str, **params):
    return client.post("/api/media", content=data, headers={"Content-Type": content_type}, params=params)


def upload_file(client, path, content_type: str) -> dict:
    res = post(client, path.read_bytes(), content_type)
    assert res.status_code == 201, res.text
    return res.json()


def stored(media_id: str = ""):
    root = api.media_store.root
    return sorted(p.name for p in root.iterdir()) if root.is_dir() and not media_id else (
        sorted(p.name for p in (root / media_id).iterdir()) if media_id else [])


def assert_detail(res, status: int, *says: str) -> str:
    assert res.status_code == status, res.text
    body = res.json()
    assert set(body) == {"detail"} and isinstance(body["detail"], str), body
    for words in says:
        assert words in body["detail"]
    return body["detail"]


# ─── What is taken ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", list(KINDS))
def test_every_audio_and_video_type_is_taken_and_its_sound_kept_three_ways(client, ffmpeg, made, kind):
    import soundfile as sf

    path, content_type = make_kind(ffmpeg, kind, made)

    body = upload_file(client, path, content_type)

    assert set(body) == {"media_id", "duration", "sample_rate", "channels", "has_audio"}
    assert HEX32.fullmatch(body["media_id"])
    assert body["duration"] == pytest.approx(2.0, abs=0.06)
    assert (body["sample_rate"], body["channels"], body["has_audio"]) == (48000, 1, True)
    assert stored(body["media_id"]) == ["meta.json", "rhythm.wav", "sound.wav", "speech.wav"]
    folder = api.media_store.root / body["media_id"]
    assert (sf.info(str(folder / "speech.wav")).samplerate, sf.info(str(folder / "speech.wav")).channels) == (16000, 1)
    assert (sf.info(str(folder / "rhythm.wav")).samplerate, sf.info(str(folder / "rhythm.wav")).channels) == (22050, 1)


def test_the_sound_is_kept_at_its_own_rate_and_channels(client, ffmpeg, tmp_path):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(44100, channels=2), 44100)

    body = upload_file(client, path, "audio/x-wav")

    assert (body["duration"], body["sample_rate"], body["channels"]) == (3.0, 44100, 2)


def test_the_content_type_s_parameters_and_case_do_not_matter(client, ffmpeg, made):
    path, _ = make_kind(ffmpeg, "wav", made)

    res = post(client, path.read_bytes(), "Audio/WAV; codecs=1")

    assert res.status_code == 201, res.text


def test_a_track_that_starts_late_is_kept_on_the_media_s_own_time(client, ffmpeg, made):
    """The audio stream starts half a second into the video: its first sample
    is padded to there, so every time answered is a time in the video."""
    media_id = upload_file(client, video_with_late_audio(ffmpeg, made), "video/mp4")["media_id"]

    silences = client.post(f"/api/media/{media_id}/analyze", params={"features": "silence",
                                                                     "silence_min": 0.3}).json()["silences"]

    assert silences[0]["start"] == 0.0
    assert silences[0]["end"] == pytest.approx(0.5, abs=0.03)


# ─── What is refused ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("content_type", ["text/plain", "image/png", "application/octet-stream",
                                          "audio/x-unknown", "video/x-msvideo", ""])
def test_a_type_joe_does_not_take_is_415(client, content_type):
    res = client.post("/api/media", content=b"RIFF....", headers={"Content-Type": content_type} if content_type else {})

    detail = assert_detail(res, 415, "unsupported media type", "audio/wav", "video/mp4")
    assert f"'{content_type or 'none'}'" in detail
    assert stored() == []


def test_a_file_ffmpeg_cannot_decode_is_422(client, ffmpeg):
    assert_detail(post(client, b"this is not a sound at all", "audio/wav"), 422, "no audio ffmpeg can decode")
    assert_detail(post(client, b"", "video/mp4"), 422, "no audio")
    assert stored() == []


def test_a_video_with_no_sound_track_is_422(client, ffmpeg, made):
    res = post(client, video_without_audio(ffmpeg, made).read_bytes(), "video/mp4")

    assert_detail(res, 422, "this media has no audio stream")
    assert stored() == []


@pytest.mark.parametrize("script", [
    b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:2.0,\nother.wav\n#EXT-X-ENDLIST\n",
    b"ffconcat version 1.0\nfile 'other.wav'\n",
], ids=["playlist", "concat"])
def test_a_playlist_or_concat_script_sent_as_media_is_422(client, ffmpeg, script):
    assert_detail(post(client, script, "audio/wav"), 422)
    assert stored() == []


def test_a_concat_script_beside_a_sound_reads_no_other_file(ffmpeg, made, tmp_path):
    """ffmpeg opens an upload only with the demuxers of the formats joe takes:
    a concat script would otherwise read the file it names into the sound.
    Mutation: drop `-format_whitelist` -- the script reads other.wav, red."""
    other, _ = make_kind(ffmpeg, "wav", made)
    (tmp_path / "other.wav").write_bytes(other.read_bytes())
    script = tmp_path / "upload.wav"
    script.write_text("ffconcat version 1.0\nfile 'other.wav'\n")
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(Media.MediaError) as refused:
        Media.extract(script, out, ffmpeg)

    assert refused.value.status == 422


def test_a_body_larger_than_the_cap_is_413_by_its_length(client, tmp_path, monkeypatch):
    """Judged on the header, before a byte is read -- and before ffmpeg is
    looked for, so here, with none, only that judgement can answer 413."""
    monkeypatch.setenv("JOE_MEDIA_MAX_BYTES", "1000")
    monkeypatch.setenv("JOE_FFMPEG", str(tmp_path / "no-ffmpeg-here.exe"))

    res = post(client, b"\0" * 1001, "audio/wav")

    assert_detail(res, 413, "larger than 1000 bytes", "JOE_MEDIA_MAX_BYTES")
    assert stored() == []


def test_a_body_larger_than_the_cap_is_413_while_it_arrives(client, monkeypatch):
    """No Content-Length to judge by: counted as it is written, and refused at
    the cap. The ffmpeg named is never run."""
    monkeypatch.setenv("JOE_MEDIA_MAX_BYTES", "1000")
    monkeypatch.setenv("JOE_FFMPEG", sys.executable)

    def body():
        for _ in range(5):
            yield b"\0" * 300

    res = client.post("/api/media", content=body(), headers={"Content-Type": "audio/wav"})

    assert_detail(res, 413, "larger than 1000 bytes")
    assert stored() == []


def test_a_sound_longer_than_the_cap_is_413(client, ffmpeg, made, monkeypatch):
    monkeypatch.setenv("JOE_MEDIA_MAX_SECONDS", "1.5")
    path, content_type = make_kind(ffmpeg, "wav", made)

    assert_detail(post(client, path.read_bytes(), content_type), 413, "longer than 1.5 seconds")
    assert stored() == []


def test_no_ffmpeg_is_503_and_says_how_to_name_one(client, tmp_path, monkeypatch):
    monkeypatch.setenv("JOE_FFMPEG", str(tmp_path / "no-ffmpeg-here.exe"))

    assert_detail(post(client, b"RIFF", "audio/wav"), 503, "ffmpeg", "JOE_FFMPEG")


# ─── How long an upload is kept ───────────────────────────────────────────────

def test_delete_removes_the_upload_and_its_files(client, ffmpeg, made):
    path, content_type = make_kind(ffmpeg, "wav", made)
    media_id = upload_file(client, path, content_type)["media_id"]

    res = client.delete(f"/api/media/{media_id}")

    assert res.status_code == 204 and res.content == b""
    assert stored() == []
    assert_detail(client.delete(f"/api/media/{media_id}"), 404, "no such media")
    assert_detail(client.post(f"/api/media/{media_id}/analyze"), 404, "no such media")


@pytest.mark.parametrize("media_id", ["0" * 32, "capabilities", "ZZ" * 16, "..%2F..%2Fpyproject.toml"])
def test_an_id_joe_never_gave_is_404(client, media_id):
    assert_detail(client.delete(f"/api/media/{media_id}"), 404)
    assert_detail(client.post(f"/api/media/{media_id}/analyze"), 404)


def test_an_upload_expires_an_hour_after_its_last_use_and_is_swept(client, ffmpeg, made, tmp_path, monkeypatch):
    now = [1_000_000.0]
    store = MediaStore(root=tmp_path / "kept", ttl_seconds=3600, clock=lambda: now[0])
    monkeypatch.setattr(api, "media_store", store)
    path, content_type = make_kind(ffmpeg, "wav", made)
    media_id = upload_file(client, path, content_type)["media_id"]

    now[0] += 3500
    assert client.post(f"/api/media/{media_id}/analyze", params={"features": "peaks"}).status_code == 200
    now[0] += 3500  # 7000 s after the upload, 3500 after its last use
    assert client.post(f"/api/media/{media_id}/analyze", params={"features": "peaks"}).status_code == 200
    now[0] += 3601

    assert_detail(client.post(f"/api/media/{media_id}/analyze"), 404, "expired")
    assert store.sweep() == [media_id]
    assert not (store.root / media_id).exists()


def test_the_server_sweeps_while_it_runs(monkeypatch):
    swept = threading.Event()
    monkeypatch.setattr(api.media_store, "sweep", lambda: swept.set() or [])

    with TestClient(api.app):
        assert swept.wait(5)
        assert any(t.name == "joe-media-sweep" for t in threading.enumerate())
    for t in threading.enumerate():
        if t.name == "joe-media-sweep":
            t.join(5)
            assert not t.is_alive()


# ─── Analysis by id ───────────────────────────────────────────────────────────

def test_an_analysis_answers_every_feature_in_v1_s_shape(client, ffmpeg, tmp_path):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)
    media_id = upload_file(client, path, "audio/wav")["media_id"]

    res = client.post(f"/api/media/{media_id}/analyze",
                      params={"features": "tempo,beats,onsets,loudness,silence,peaks"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert list(body) == ["duration", "tempo", "beats", "onsets", "loudness", "silences", "peaks"]
    assert body["duration"] == 3.0
    assert body["tempo"] is None or isinstance(body["tempo"], float)
    assert all(isinstance(t, float) for t in body["beats"] + body["onsets"])
    assert body["onsets"][0] == pytest.approx(1.0, abs=0.03)
    assert body["loudness"]["rms_db"] == pytest.approx(-13.8, abs=0.05)
    assert body["loudness"]["peak_db"] == pytest.approx(-6.02, abs=0.05)
    # Gated: the silent seconds do not count, so it is the tone's loudness --
    # about -6.6 LUFS over whole blocks, less over the blocks at its edges.
    assert body["loudness"]["lufs"] == pytest.approx(-7.8, abs=0.3)
    assert body["silences"] == [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]
    assert body["peaks"]["rate"] == Analysis.DEFAULT_PEAKS_RATE
    values = body["peaks"]["values"]
    assert len(values) == 150 and values[:50] == [0.0] * 50 and values[50:100] == [0.5] * 50


def test_no_features_named_is_every_feature(client, ffmpeg, tmp_path):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)
    media_id = upload_file(client, path, "audio/wav")["media_id"]

    for params in ({}, {"features": ""}):
        body = client.post(f"/api/media/{media_id}/analyze", params=params).json()
        assert list(body) == ["duration", "tempo", "beats", "onsets", "loudness", "silences", "peaks"]


def test_a_click_track_s_tempo_through_upload_and_analysis(client, ffmpeg, tmp_path):
    y, clicks = click_track(120, 12, 44100)
    media_id = upload_file(client, write_wav(tmp_path / "clicks.wav", y, 44100), "audio/wav")["media_id"]

    body = client.post(f"/api/media/{media_id}/analyze", params={"features": "tempo,beats"}).json()

    assert set(body) == {"duration", "tempo", "beats"}
    assert body["tempo"] == pytest.approx(120, rel=0.02)
    beats = np.array(body["beats"])
    assert np.abs(beats[:, None] - clicks[None, :]).min(axis=1).max() < 0.04


def test_only_the_features_asked_for_are_answered(client, ffmpeg, tmp_path):
    path = write_wav(tmp_path / "sts.wav", silence_tone_silence(), 44100)
    media_id = upload_file(client, path, "audio/wav")["media_id"]

    body = client.post(f"/api/media/{media_id}/analyze",
                       params={"features": " Peaks , silence", "peaks_rate": 4, "silence_db": -30,
                               "silence_min": 1.0}).json()

    assert list(body) == ["duration", "silences", "peaks"]
    assert body["peaks"] == {"rate": 4, "values": [0.0] * 4 + [0.5] * 4 + [0.0] * 4}


def test_an_unknown_feature_is_422_naming_the_ones_there_are(client, ffmpeg, made):
    path, content_type = make_kind(ffmpeg, "wav", made)
    media_id = upload_file(client, path, content_type)["media_id"]

    assert_detail(client.post(f"/api/media/{media_id}/analyze", params={"features": "tempo,pitch"}),
                  422, "unknown feature 'pitch'", ", ".join(Analysis.FEATURES))


@pytest.mark.parametrize("params, names", [
    ({"peaks_rate": 0}, "peaks_rate"),
    ({"peaks_rate": 1001}, "peaks_rate"),
    ({"peaks_rate": "fast"}, "peaks_rate"),
    ({"silence_db": 6}, "silence_db"),
    ({"silence_min": 0}, "silence_min"),
])
def test_a_parameter_out_of_bounds_is_422_with_a_sentence_not_a_list(client, params, names):
    detail = assert_detail(client.post(f"/api/media/{'0' * 32}/analyze", params=params), 422)

    assert detail.startswith(f"{names}: ")


def test_the_rest_of_the_api_still_answers_as_fastapi_does(client):
    """The media routes' error shape is theirs alone: the voice API's
    validation errors are FastAPI's list, as they always were."""
    res = client.get("/api/voice/history", params={"limit": "many"})

    assert res.status_code == 422
    assert isinstance(res.json()["detail"], list)


def test_decoding_and_analysis_run_on_the_media_threads(client, ffmpeg, made, monkeypatch):
    """Not on the pool FastAPI answers the voice API's routes with. Mutation:
    run either with `run_in_threadpool` -- red."""
    ran_on = {}
    extract, analyze = Media.extract, Analysis.analyze
    monkeypatch.setattr(Media, "extract", lambda *a, **k: ran_on.setdefault(
        "extract", threading.current_thread().name) and extract(*a, **k))
    monkeypatch.setattr(Analysis, "analyze", lambda *a, **k: ran_on.setdefault(
        "analyze", threading.current_thread().name) and analyze(*a, **k))
    path, content_type = make_kind(ffmpeg, "wav", made)

    media_id = upload_file(client, path, content_type)["media_id"]
    assert client.post(f"/api/media/{media_id}/analyze", params={"features": "peaks"}).status_code == 200

    assert ran_on["extract"].startswith("joe-media") and ran_on["analyze"].startswith("joe-media")


def test_an_unforeseen_failure_is_a_500_in_the_same_shape(client, ffmpeg, made, monkeypatch):
    path, content_type = make_kind(ffmpeg, "wav", made)
    media_id = upload_file(client, path, content_type)["media_id"]
    monkeypatch.setattr(Analysis, "analyze", lambda *a, **k: 1 / 0)

    assert_detail(client.post(f"/api/media/{media_id}/analyze"), 500, "ZeroDivisionError")


def test_ffmpeg_makes_what_the_fixtures_ask_for(ffmpeg, tmp_path):
    """The fixture maker itself: a failure names the file and ffmpeg's reason."""
    with pytest.raises(RuntimeError, match="could not make nothing.wav"):
        ffmpeg_make(ffmpeg, tmp_path / "nothing.wav", "-f", "lavfi", "-i", "no-such-source")


def test_media_s_formats_are_v1_s_audio_and_video():
    extensions = set(Media.FORMATS.values())

    assert extensions == {"wav", "mp3", "ogg", "flac", "m4a", "aac", "webm", "mp4", "mov", "mkv"}
    assert all(t.split("/")[0] in ("audio", "video") for t in Media.FORMATS)
