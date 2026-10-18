"""The media store: private directories, a TTL counted from the last use, and
nothing removed from under a request that is using it.

No ffmpeg: the uploads here are directories with a `meta.json`, as `commit`
writes them.
"""

import os
import time

import pytest

from Modules.Media import MediaError, MediaStore, Sound

SOUND = Sound(duration=2.0, sample_rate=48000, channels=2)


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return MediaStore(root=tmp_path / "media", ttl_seconds=60, clock=clock)


def upload(store) -> str:
    with store.receiving() as (media_id, folder):
        (folder / "sound.wav").write_bytes(b"RIFF")
        store.commit(media_id, SOUND)
    return media_id


def test_an_upload_has_a_private_directory_named_by_a_random_id(store):
    a, b = upload(store), upload(store)

    assert a != b and len(a) == 32 and int(a, 16) >= 0
    assert (store.root / a / "meta.json").is_file()
    with store.use(a) as media:
        assert media.answer() == {"media_id": a, "duration": 2.0, "sample_rate": 48000,
                                  "channels": 2, "has_audio": True}


def test_an_upload_that_never_arrives_leaves_nothing(store):
    with pytest.raises(RuntimeError):
        with store.receiving() as (_, folder):
            (folder / "upload.wav").write_bytes(b"half")
            raise RuntimeError("the client went away")

    assert list(store.root.iterdir()) == []


def test_an_upload_expires_ttl_seconds_after_its_last_use(store, clock):
    media_id = upload(store)

    clock.now += 59
    with store.use(media_id):
        pass  # used: its time starts again
    clock.now += 59
    assert store.sweep() == []
    with store.use(media_id):
        pass

    clock.now += 61
    with pytest.raises(MediaError) as gone:
        with store.use(media_id):
            pass
    assert gone.value.status == 404
    assert store.sweep() == [media_id]
    assert not (store.root / media_id).exists()


def test_an_upload_in_use_is_not_swept_however_old(store, clock):
    media_id = upload(store)

    with store.use(media_id):
        clock.now += 3600
        assert store.sweep() == []
        assert (store.root / media_id / "sound.wav").exists()
    clock.now += 61
    assert store.sweep() == [media_id]


def test_one_deleted_while_in_use_goes_when_its_use_ends(store):
    media_id = upload(store)

    with store.use(media_id):
        store.delete(media_id)
        assert (store.root / media_id / "sound.wav").exists()  # still being read
        with pytest.raises(MediaError):
            with store.use(media_id):
                pass  # but nobody new may use it
        with pytest.raises(MediaError):
            store.delete(media_id)
    assert not (store.root / media_id).exists()


def test_delete_removes_an_upload_at_once(store):
    media_id = upload(store)

    store.delete(media_id)

    assert not (store.root / media_id).exists()
    with pytest.raises(MediaError) as gone:
        store.delete(media_id)
    assert gone.value.status == 404


@pytest.mark.parametrize("media_id", ["", "..", "../media", "A" * 32, "a" * 31, "a" * 33,
                                      "a" * 31 + "/", "a" * 31 + "g"])
def test_an_id_that_is_not_one_reaches_no_file(store, media_id):
    for act in (lambda: store.use(media_id).__enter__(), lambda: store.delete(media_id)):
        with pytest.raises(MediaError) as refused:
            act()
        assert refused.value.status == 404


def test_the_sweep_leaves_what_is_not_an_upload_and_waits_for_one_arriving(store, tmp_path):
    store.root.mkdir(parents=True)
    (store.root / "notes.txt").write_text("mine")
    (store.root / "keep-me").mkdir()
    stale = store.root / ("b" * 32)  # an upload a crash interrupted, long ago
    stale.mkdir()
    old = time.time() - 3600
    os.utime(stale, (old, old))
    fresh = store.root / ("c" * 32)  # one arriving now, perhaps in another process
    fresh.mkdir()

    assert store.sweep() == ["b" * 32]
    assert sorted(p.name for p in store.root.iterdir()) == ["c" * 32, "keep-me", "notes.txt"]


def test_an_upload_still_arriving_is_not_swept(store, clock):
    with store.receiving() as (media_id, folder):
        clock.now += 3600
        os.utime(folder, (0, 0))
        assert store.sweep() == []
        store.commit(media_id, SOUND)
    with store.use(media_id):
        pass
