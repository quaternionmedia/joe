"""One take's recording, served for the visualiser by the take's id."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.io import wavfile

import api


def _recording(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), 16000, np.zeros(1600, dtype=np.int16))
    return path


def test_a_take_s_recording_is_served_by_its_id():
    """Mutation: serve nothing -- red."""
    path = _recording(api.datapoints.root / "capture_test.wav")
    api.datapoints.write("take", take="a1b2c3", text="approve", source="voice", audio=str(path))

    served = TestClient(api.app).get("/api/voice/takes/a1b2c3/audio")

    assert served.status_code == 200 and served.headers["content-type"] == "audio/wav"
    assert served.content == path.read_bytes()


def test_an_unknown_take_or_a_malformed_id_is_refused():
    client = TestClient(api.app)

    assert client.get("/api/voice/takes/ffffff/audio").status_code == 404
    assert client.get("/api/voice/takes/not-hex/audio").status_code == 400


def test_a_record_kept_relative_to_the_voice_folder_is_served():
    path = _recording(api.datapoints.root / "capture_rel.wav")
    api.datapoints.write("take", take="b1b2b3", text="x", source="voice", audio="capture_rel.wav")

    served = TestClient(api.app).get("/api/voice/takes/b1b2b3/audio")

    assert served.status_code == 200 and served.content == path.read_bytes()


@pytest.mark.parametrize("where_it_was", [
    r"D:\old-clone\Data\Voice\capture_moved.wav",
    "/srv/old-clone/Data/Voice/capture_moved.wav",
])
def test_a_record_naming_where_the_voice_folder_was_is_found_by_its_file_name(where_it_was):
    """Mutation: drop the look-up by name -- red."""
    path = _recording(api.datapoints.root / "capture_moved.wav")
    api.datapoints.write("take", take="c1c2c3", text="x", source="voice", audio=where_it_was)

    served = TestClient(api.app).get("/api/voice/takes/c1c2c3/audio")

    assert served.status_code == 200 and served.content == path.read_bytes()


def test_a_name_that_climbs_out_of_the_voice_folder_is_still_refused():
    api.datapoints.write("take", take="e1e2e3", text="x", source="voice", audio=r"D:\old\..")

    assert TestClient(api.app).get("/api/voice/takes/e1e2e3/audio").status_code == 404


def test_a_recording_outside_joe_s_voice_folder_is_never_served(tmp_path):
    """Whatever the record names. Mutation: drop the folder check -- red."""
    outside = _recording(tmp_path / "elsewhere" / "secret.wav")
    api.datapoints.write("take", take="d4e5f6", text="x", source="voice", audio=str(outside))

    assert TestClient(api.app).get("/api/voice/takes/d4e5f6/audio").status_code == 404
