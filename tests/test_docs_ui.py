"""docs/ui.md against the page it describes: every window the registry has, in
its order, each under its id, and the key the arrangement is kept under."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def registry_ids():
    text = (ROOT / "src" / "layout" / "registry.js").read_text(encoding="utf-8")
    return re.findall(r"\{ id: '([a-z]+)', title:", text)


def page():
    return (ROOT / "docs" / "ui.md").read_text(encoding="utf-8")


def test_the_registry_is_read():
    assert registry_ids()[0] == "visualiser"


def test_every_window_has_a_section_under_its_id_in_registry_order():
    windows = page().split("\n## Windows\n", 1)[1].split("\n## ", 1)[0]
    assert re.findall(r"^### .+\n\nId `([a-z]+)`\.", windows, re.M) == registry_ids()


def test_the_key_the_arrangement_is_kept_under_is_named():
    saved = (ROOT / "src" / "layout" / "saved_layout.js").read_text(encoding="utf-8")
    key = re.search(r"LAYOUT_KEY = '([^']+)'", saved).group(1)
    assert f"`{key}`" in page()
