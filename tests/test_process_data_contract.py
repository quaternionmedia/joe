"""The specs load tests/e2e/fixtures/Process_Data_fixture.json as the pipeline's
output: it has the shape save_json writes, key for key, so the page the specs
check reads what the pipeline makes."""

import json
from pathlib import Path
from types import SimpleNamespace

from Modules.utilities import save_json

FIXTURE = Path(__file__).resolve().parent / "e2e" / "fixtures" / "Process_Data_fixture.json"


def shape(value):
    """Keys all the way down; a list by its first item."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()} if not _named(value) else \
            {"*": shape(next(iter(value.values())))}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__ if isinstance(value, (str, bool)) else "number"


def _named(mapping):
    """A mapping keyed by a recording's name or a transform type, not by field."""
    return bool(mapping) and all(isinstance(v, dict) and ("chroma" in v or "midi" in v) for v in mapping.values())


def test_the_specs_fixture_has_the_shape_the_pipeline_writes(tmp_path):
    note = SimpleNamespace(note="C4", pitch=60, start_dur=[(0.5, 0.25)])
    chroma = SimpleNamespace(file_path="c.png", midi=SimpleNamespace(file_path="m.mid", notes=[note]))
    audio = SimpleNamespace(name="take", file_path="take.wav", sr=22050, full_chroma_path="full.png",
                            chromas={"Raw": chroma})
    save_json("01-01-26_00-00-00", tmp_path, 0.1, [512], 0.3, 0.3, [0.5], ["take.wav"], [audio])

    written = json.loads((tmp_path / "Process_Data_01-01-26_00-00-00.json").read_text())
    assert shape(json.loads(FIXTURE.read_text(encoding="utf-8"))) == shape(written)
