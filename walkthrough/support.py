"""What the walkthrough pages need that prose cannot hold.

Not a demo harness. Per the one-executable-walkthrough record, the picture a
reader sees has to come out of the same execution as an assertion about what
the code did, against the real component. So these helpers start the real API
and the real Vite dev server, drive the real page in a real browser, and record
what they saw. They assert nothing about behaviour themselves; the pages do,
in the same run that takes the picture.
"""

from __future__ import annotations

import atexit
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# `joe check` points the shutter elsewhere, so a check of a joe somebody else
# started writes no picture into the checkout.
MEDIA = Path(os.environ.get("JOE_WALKTHROUGH_SHOTS") or Path(__file__).resolve().parent / "media")

# How long a server gets to answer before it is called unreachable. Generous:
# a cold start on Windows imports whisper and torch before uvicorn listens.
STARTUP_TIMEOUT = 90.0


# Everything that has to be undone, however the run ends.
#
# doctest stops at a page's first failing example, so teardown written at the
# bottom of a page is never reached by the run that most needs it. Registering
# here instead means a failing page costs a red build and nothing else: no
# server left holding a port, no fixture left in the checkout's Data/.
_LEAVING: list = []


def _teardown() -> None:
    while _LEAVING:
        undo = _LEAVING.pop()
        try:
            undo()
        except Exception:
            # At interpreter exit a raise is noise printed after the report.
            pass


atexit.register(_teardown)


class Unreachable(RuntimeError):
    """The runtime a runtime-bound page needs is not there.

    Raised, never skipped. A skip is not a pass: a page that vanishes into a
    skip count when its browser is missing reports green for a demonstration
    nobody ran.
    """


def _port(taken: tuple[int, ...] = ()) -> int:
    """A port nothing is listening on, and not one of `taken`.

    `JOE_WALKTHROUGH_PORTS=lo-hi` keeps the choice inside a range, for a
    machine where several sessions share the port space; otherwise the
    operating system picks one. `taken` matters because a port is only free
    until something binds it: asked twice before either server starts, a
    range answers the same port both times.
    """
    span = os.environ.get("JOE_WALKTHROUGH_PORTS")
    candidates = [0] * 8   # the OS chooses; asked again if it repeats one
    if span:
        lo, hi = (int(part) for part in span.split("-"))
        candidates = range(lo, hi + 1)
    for candidate in candidates:
        if candidate and candidate in taken:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            port = probe.getsockname()[1]
            if port not in taken:
                return port
    raise Unreachable(f"no free port in JOE_WALKTHROUGH_PORTS={span}")


def _stop(process: subprocess.Popen) -> None:
    """Stop a process and everything it started.

    On Windows `terminate()` reaches only the direct child, and Vite's esbuild
    service is a grandchild; `taskkill /T` takes the tree, as `joe dev` does.
    """
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       check=False, capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as answer:
            return answer.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def arpeggio(rate: int = 22050) -> bytes:
    """The fixture: C4, E4, G4 and C5, half a second each, as a WAV file.

    Made rather than committed, so the page shows what it is. Each note has
    five partials falling off as 1/n, because the pipeline's harmonic check
    looks for overtones and a bare sine has none.
    """
    import numpy as np
    import soundfile

    def note(midi: int, seconds: float = 0.5):
        frequency = 440.0 * 2 ** ((midi - 69) / 12)
        t = np.arange(int(seconds * rate)) / rate
        tone = sum(np.sin(2 * np.pi * frequency * k * t) / k for k in range(1, 6))
        # 10 ms in and 50 ms out, so no note starts or ends on a click.
        return tone * np.minimum(1.0, np.minimum(t / 0.01, (seconds - t) / 0.05))

    signal = np.concatenate([note(m) for m in (60, 64, 67, 72)])
    signal = 0.5 * signal / np.abs(signal).max()
    out = io.BytesIO()
    soundfile.write(out, signal, rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


class LiveApp:
    """joe's API and its Vite dev server, each on a port of its own.

    Ports of their own rather than 8000 and 3000: a developer's `joe dev` is
    usually up, and a page that quietly measured that one would be testing
    whatever code happened to be running rather than the code in the tree.
    The dev server is pointed at this API with `JOE_API_URL`, and at a qmcp
    nobody runs with `QMCP_URL`, so a developer's qmcp cannot put its queue
    into the picture.

    With `JOE_WALKTHROUGH_URL` set -- `joe check --url` sets it -- the page is
    pointed at a joe on purpose: it attaches to the dev server answering there
    and reaches the API through that server's proxy, starts nothing, and
    leaves that joe's Data/ to whoever started it.
    """

    def __init__(self) -> None:
        self.uploaded: list[str] = []
        attached = os.environ.get("JOE_WALKTHROUGH_URL")
        self.attached = bool(attached)
        if attached:
            parts = urllib.parse.urlsplit(attached)
            self.web = self.api = f"{parts.scheme}://{parts.netloc}"
            self.logs = None
            return
        self.api_port = _port()
        self.web_port = _port(taken=(self.api_port,))
        self.api = f"http://127.0.0.1:{self.api_port}"
        self.web = f"http://127.0.0.1:{self.web_port}"
        self.logs = Path(tempfile.mkdtemp(prefix="joe-walkthrough-"))
        _LEAVING.append(lambda: shutil.rmtree(self.logs, ignore_errors=True))

    def start(self) -> "LiveApp":
        if self.attached:
            for url in (f"{self.web}/joe/", f"{self.api}/api/health"):
                if not _answers(url):
                    raise Unreachable(f"{url} does not answer")
            return self
        node = shutil.which("node")
        if node is None:
            raise Unreachable("node is not on PATH; the page is served by Vite")
        vite = REPO / "node_modules" / "vite" / "bin" / "vite.js"
        if not vite.exists():
            raise Unreachable(f"{vite} is missing: run `npm ci` first")

        # The folders under Data/ before anything ran, so the ones this run
        # makes can be told apart afterwards. Registered first in the list,
        # so it runs last: after the servers have stopped, since Windows will
        # not remove a file or folder a live process still holds.
        before = _folders()
        _LEAVING.insert(0, lambda: _tidy(self.uploaded, before))

        quiet = {**os.environ, "JOE_CUES": "0", "JOE_DATAPOINTS": "0"}
        self._spawn("api", [sys.executable, "-m", "uvicorn", "api:app",
                            "--host", "127.0.0.1", "--port", str(self.api_port),
                            "--log-level", "warning"], quiet)
        self._await("api", f"{self.api}/api/health")

        nobody = f"http://127.0.0.1:{_port(taken=(self.api_port, self.web_port))}"
        served = {**os.environ, "JOE_API_URL": self.api, "QMCP_URL": nobody}
        self._spawn("web", [node, str(vite), "--port", str(self.web_port),
                            "--strictPort", "--host", "127.0.0.1"], served)
        self._await("web", f"{self.web}/joe/")
        return self

    def _spawn(self, name: str, command: list[str], env: dict) -> None:
        # A file rather than a pipe: Vite logs every refused proxy request,
        # and a pipe nobody reads fills and stops the server mid-page.
        log = open(self.logs / f"{name}.log", "wb")
        process = subprocess.Popen(command, cwd=REPO, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        setattr(self, f"_{name}", process)
        _LEAVING.append(lambda: (_stop(process), log.close()))

    def _await(self, name: str, url: str) -> None:
        process = getattr(self, f"_{name}")
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise Unreachable(f"the {name} server exited before answering:\n"
                                  f"{self.log(name)}")
            if _answers(url):
                return
            time.sleep(0.25)
        raise Unreachable(f"{url} never answered:\n{self.log(name)}")

    def log(self, name: str) -> str:
        if self.logs is None:
            return ""
        path = self.logs / f"{name}.log"
        return path.read_text(encoding="utf-8", errors="replace")[-2000:] if path.exists() else ""

    def get(self, path: str):
        """GET one of the API's routes, as the page's own fetch would."""
        with urllib.request.urlopen(f"{self.api}{path}", timeout=10) as answer:
            return json.loads(answer.read())

    def upload(self, wav: bytes) -> str:
        """Hand the API a recording through its own upload route.

        The route the page's recorder posts to, so the file lands where the
        page's own recordings do: `Data/Audio/` in this checkout. The file,
        every output the pipeline writes for it, and any folder the run made
        are removed when the run ends, so the checkout's Data/ is as it was.
        """
        request = urllib.request.Request(
            f"{self.api}/api/audio/upload", data=wav, method="POST",
            headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(request, timeout=10) as answer:
            name = json.loads(answer.read())["filename"]
        self.uploaded.append(name)
        return name

    def open(self, browser, width: int = 1400, height: int = 800):
        """A real browser on the real page, with its console kept.

        A browser error never reaches either server's log, so it is captured
        here and the page asserts it is empty.
        """
        page = browser.new_page(viewport={"width": width, "height": height})
        page.errors = []
        page.failed = set()
        page.on("pageerror", lambda error: page.errors.append(str(error)))
        page.on("console", lambda message: _console(page, message))
        # Every request the page made that was refused, by status and path,
        # so a page can say which failures it expects rather than none.
        page.on("response", lambda response:
                page.failed.add(f"{response.status} {urllib.parse.urlsplit(response.url).path}")
                if response.status >= 400 else None)
        # `load`, not `networkidle`: the voice panel holds an event stream
        # open for the life of the page, so the network is never idle.
        page.goto(f"{self.web}/joe/", wait_until="load")
        # p5 is the one thing the page takes from the network. Without it the
        # module that wires every control throws at its first line, and what
        # follows would fail somewhere unrelated, so it is named here.
        if page.evaluate("typeof window.p5") != "function":
            raise Unreachable("p5 is loaded from cdn.jsdelivr.net and did not "
                              "arrive: this page needs the network")
        until(page, "() => !!document.querySelector('#sketch canvas')")
        return page


def _console(page, message) -> None:
    """Keep the console's errors, except the browser's echo of a refused request.

    Chromium logs "Failed to load resource" for every response of 400 or more,
    without saying which. Those are in `page.failed`, by path, where a page
    can tell an expected one from a defect; here they would only be noise.
    """
    if message.type != "error":
        return
    if message.text.startswith("Failed to load resource"):
        return
    page.errors.append(f"console.error: {message.text}")


def _folders() -> set[Path]:
    data = REPO / "Data"
    return {data, *(p for p in data.rglob("*") if p.is_dir())} if data.exists() else set()


def _tidy(uploaded: list[str], before: set[Path]) -> None:
    """Remove the fixtures, what the pipeline wrote for them, and new folders.

    Only files named for a fixture are removed, and only folders this run
    made, and only once they are empty, so nothing a developer put in Data/
    is touched; a fresh clone is left without a Data/ it never had.
    """
    output = REPO / "Data" / "Output"
    for name in uploaded:
        (REPO / "Data" / "Audio" / name).unlink(missing_ok=True)
        stem = Path(name).stem
        for run in (output.glob("*/") if output.exists() else []):
            written = any(run.glob(f"**/{stem}_*"))
            mentions = any(name in path.read_text(encoding="utf-8", errors="replace")
                           for path in run.glob("Process_Data_*.json"))
            if written or mentions:
                shutil.rmtree(run, ignore_errors=True)
    # Deepest first. A file Windows has been told to delete stays listed until
    # the last handle on it closes, and the API that served it can take a
    # moment to die, so a folder gets a few seconds to empty.
    for folder in sorted(_folders() - before, key=lambda p: len(p.parts), reverse=True):
        deadline = time.monotonic() + 5
        while folder.is_dir():
            try:
                folder.rmdir()
            except OSError:
                if time.monotonic() > deadline:
                    break
                time.sleep(0.2)


def painted(page, rgb_test: str) -> int:
    """How many pixels of the piano roll pass a colour test, read off the canvas.

    `rgb_test` is a JavaScript expression over `r`, `g`, `b` and `a`. Only
    strokes the roll draws at full strength count: its guide lines are drawn
    at 8% and its labels at 22%, so `a > 150` leaves them out.
    """
    return page.evaluate(
        """(test) => {
            const canvas = document.getElementById('piano-roll-canvas');
            const { data } = canvas.getContext('2d')
                .getImageData(0, 0, canvas.width, canvas.height);
            const pass = new Function('r', 'g', 'b', 'a', 'return ' + test);
            let n = 0;
            for (let i = 0; i < data.length; i += 4)
                if (pass(data[i], data[i + 1], data[i + 2], data[i + 3])) n++;
            return n;
        }""",
        rgb_test,
    )


class Shots:
    """A screenshot library that only ever records.

    It never compares and never gates. A test that diffs images fails on a
    font and gets switched off, taking the assertions beside it; the
    regression protection is the page's assertions, and the picture is a
    byproduct of the render they ran against. What it does assert is that it
    wrote what it said it wrote.
    """

    # Two frames with no animation running, so a shot lands on a settled
    # screen rather than wherever an anime.js slide happened to be.
    SETTLE = """() => new Promise(resolve => {
        const idle = () => !document.getAnimations
            || document.getAnimations().every(a => a.playState !== 'running');
        requestAnimationFrame(() => requestAnimationFrame(() => resolve(idle())));
    })"""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.written: list[Path] = []
        MEDIA.mkdir(parents=True, exist_ok=True)

    def take(self, page, name: str, of: str | None = None) -> str:
        """Record the page, or only the element `of` selects."""
        path = MEDIA / f"{self.slug}-{name}.png"
        path.unlink(missing_ok=True)
        page.wait_for_function(self.SETTLE, timeout=10_000)
        if of is None:
            page.screenshot(path=str(path))
        else:
            page.locator(of).screenshot(path=str(path))
        if not path.exists() or path.stat().st_size == 0:
            raise AssertionError(f"screenshot {path.name} was not written")
        self.written.append(path)
        return path.name


def chromium():
    """A browser that shuts itself down, however the page ends."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise Unreachable("the playwright package is missing: uv sync") from error

    driver = sync_playwright().start()
    _LEAVING.append(driver.stop)
    try:
        browser = driver.chromium.launch()
    except Exception as error:
        raise Unreachable(
            "Chromium would not launch: uv run playwright install chromium"
        ) from error
    _LEAVING.append(browser.close)
    # Released by the page when it is done, not at interpreter exit:
    # Playwright's sync driver keeps an event loop running in this thread, and
    # a test collected after the page that calls `asyncio.run` would fail.
    def release() -> None:
        browser.close()
        driver.stop()

    browser.release = release
    return browser


def until(page, predicate: str, timeout: int = 15_000) -> None:
    """Wait for a condition, not for a number of milliseconds.

    Fails naming the condition that never held, so a slow machine produces
    a message rather than a puzzle.
    """
    try:
        page.wait_for_function(predicate, timeout=timeout)
    except Exception as error:  # noqa: BLE001 - re-raised with the predicate
        raise AssertionError(
            f"waited {timeout} ms and this never became true:\n  {predicate}"
        ) from error
