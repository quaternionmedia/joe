"""POST /api/audio/upload: judged before it is read, written as it arrives.

The library's upload once read the whole body into memory and only then
asked whether it was over 100 MB, so a body of any size was held whole. Now
the type and the declared length are judged first, the body goes to disk as
it arrives, out of every route's reach, and only a whole upload enters the
library.
"""

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture
def library(tmp_path, monkeypatch):
    folder = tmp_path / "Data" / "Audio"
    monkeypatch.setattr(api, "AUDIO_DIR", folder)
    return folder


@pytest.fixture
def client(library):
    return TestClient(api.app)


def kept(library) -> list[str]:
    return sorted(p.name for p in library.iterdir() if p.is_file()) if library.exists() else []


def incoming(library) -> list[str]:
    folder = library / ".incoming"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_an_upload_enters_the_library_whole(client, library):
    response = client.post("/api/audio/upload", content=b"RIFF....WAVE", headers={"content-type": "audio/wav"})

    assert response.status_code == 200
    name = response.json()["filename"]
    assert name.startswith("capture_") and name.endswith(".wav")
    assert kept(library) == [name]
    assert (library / name).read_bytes() == b"RIFF....WAVE"
    assert incoming(library) == []
    assert [f["name"] for f in client.get("/api/audio/files").json()] == [name]


def test_a_type_joe_does_not_take_is_refused_before_its_length(client, library):
    response = client.post("/api/audio/upload", content=b"x",
                           headers={"content-type": "text/plain", "content-length": str(10**12)})

    assert response.status_code == 415
    assert kept(library) == []


def test_a_declared_length_over_the_cap_is_refused_before_a_byte_is_read(client, library, monkeypatch):
    def unread(*args, **kwargs):
        pytest.fail("the body was read")

    monkeypatch.setattr(api.Request, "stream", unread)
    response = client.post("/api/audio/upload", content=b"RIFF",
                           headers={"content-type": "audio/wav", "content-length": str(100 * 1024 * 1024 + 1)})

    assert response.status_code == 413
    assert response.json() == {"detail": "File too large (max 100 MB)"}
    assert kept(library) == []


def test_a_body_that_passes_the_cap_as_it_arrives_is_refused_and_nothing_is_left(client, library, monkeypatch):
    monkeypatch.setattr(api, "_UPLOAD_MAX_BYTES", 10)

    def chunks():
        yield b"RIFF"
        yield b"0123456789"

    response = client.post("/api/audio/upload", content=chunks(), headers={"content-type": "audio/webm"})

    assert response.status_code == 413
    assert kept(library) == []
    assert incoming(library) == []


def test_an_upload_on_its_way_in_is_not_served(client, library):
    (library / ".incoming").mkdir(parents=True)
    (library / ".incoming" / "capture_x.wav").write_bytes(b"RIFF")

    assert client.get("/api/audio/.incoming").status_code == 404
    assert client.get("/api/audio/files").json() == []
