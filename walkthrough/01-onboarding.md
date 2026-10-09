# 01 — Onboarding

> **Runtime: hermetic.** No port, no network, no browser. It needs this
> checkout's Python environment and Node on `PATH`. If this page passes, the
> checkout is built.

This is the first build. It is a page rather than a README section because a
README section is a claim, and this page ran on the machine reading it. Every
example below is executed by the ordinary test command:

```sh
uv run pytest tests walkthrough --doctest-glob=*.md
```

## What you need

**Python 3.11.** `pyproject.toml` pins it, and `uv` installs it when the
machine has none. The interpreter running this page is the one the project
uses:

```python
>>> import sys
>>> sys.version_info[:2]
(3, 11)

```

**uv**, from <https://docs.astral.sh/uv/>. `uv.lock` is the one lockfile;
there is no pip or pdm route. `uv` resolves on `PATH` under some shells and
not under others on the same machine; if a command fails with "uv is not
recognized", `uv --version` tells you whether this shell can see it.

**Node**, at a version the frontend's build tool accepts. The range is Vite's
own, read from the committed lockfile rather than written here twice:

```python
>>> import json, subprocess
>>> lock = json.loads(open('package-lock.json', encoding='utf-8').read())
>>> lock['packages']['node_modules/vite']['engines']['node']
'^18.0.0 || ^20.0.0 || >=22.0.0'
>>> node = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
>>> major = int(node.stdout.strip().lstrip('v').split('.')[0])
>>> major in (18, 20) or major >= 22
True

```

## Getting the dependencies

```sh
uv sync
npm ci
```

Two Playwrights, because two kinds of check drive a browser: the specs under
`tests/e2e/` use the Node package in `package-lock.json`, and the browser page
of this walkthrough uses the Python package in `uv.lock`. Each pins its own
Chromium build, so each installs its own:

```sh
npx playwright install chromium
uv run playwright install chromium
```

On Linux, add `--with-deps` to both, and install PortAudio, which the
backend's audio library binds and which its Linux wheel does not bundle:

```sh
sudo apt-get install -y libportaudio2
```

Without it the next example fails with `OSError: PortAudio library not found`,
because `capture.py` imports `sounddevice` at module scope and `api.py`
imports `capture.py`:

```python
>>> import sounddevice
>>> import api
>>> api.app.title
'Joe API'

```

## The `joe` command

`uv sync` installs the project, and with it a `joe` console script. A script
that installs and then cannot import its own modules is the failure
`pyproject.toml`'s `packages.find` exists to prevent, so the script is run
rather than looked for:

```python
>>> import shutil
>>> joe = shutil.which('joe')
>>> joe is not None
True
>>> subprocess.run([joe, '--help'], capture_output=True, text=True, check=True).returncode
0

```

`02-cookbook.md` is the command table.

## A fresh clone's first `joe run`

`joe run` runs `main.py`, which reads `Data/Audio/` under its own folder. On a
fresh clone that folder does not exist, and the pipeline makes it, says so,
and stops — **with exit status 0**, so `joe run` goes on to print "Done":

```python
>>> import pathlib, tempfile
>>> from Modules.utilities import make_directories
>>> fresh = pathlib.Path(tempfile.mkdtemp())
>>> try:
...     make_directories(str(fresh))
... except SystemExit as stop:
...     print('exit status', stop.code)
No audio files found, check directory.
exit status 0
>>> sorted(p.name for p in (fresh / 'Data').iterdir())
['Audio']
>>> shutil.rmtree(fresh)

```

That is `make_directories` run against an empty folder, which is what
`main.py` hands it. So a first `joe run` that says "Done" may have processed
nothing: put a recording in `Data/Audio/` first, or record one on the page
and use **Library → Process**, which `03-in-the-browser.md` does.

## The checks, and what each one cannot see

```sh
uv run pytest tests walkthrough --doctest-glob=*.md
npm run test:e2e
npm run build
```

- **The first** runs the Python suite and every page here, including the
  browser page, which starts its own API and dev server on ports of their own
  and needs `npm ci`, a Chromium for the Python Playwright, and the network
  (p5 comes from a CDN). It fails rather than skipping when any is missing.
  Name both directories: pytest ignores `testpaths` the moment it is handed a
  path, so `uv run pytest tests` alone runs none of these pages.
- **`npm run test:e2e`** runs the Playwright specs with joe's API mocked
  inside the browser. Outside CI it **reuses whatever is already listening on
  port 3000**, so with a `joe dev` running from another checkout, the specs
  test that checkout:

  ```python
  >>> 'reuseExistingServer: !process.env.CI' in open('playwright.config.js', encoding='utf-8').read()
  True

  ```

  Stop any other dev server first.
- **`npm run build`** warns that `outDir` is outside the project root. That is
  expected: Vite's root is `src/`.

None of them hears a microphone or a voice. `docs/manual-test-plan.md` is the
written plan for what only a person can check.
