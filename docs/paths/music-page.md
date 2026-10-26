# The music page

A person at joe's page: starting joe and seeing what it serves, analysing a
recording, recording live, and arranging the page's windows.
[ui.md](../ui.md) describes the windows themselves.

Run this lane's specs:

```bash
npx playwright test --grep @music-page
```

## 1. Start joe and open the page

1. Start joe with every part on, listening on this machine only:

   ```bash
   uv run joe dev
   ```

   The API answers at `http://127.0.0.1:8000/api/health`, and the page is at
   `http://localhost:3000/joe/`.

   - test: tests/test_cli_access.py::test_dev_with_no_allow_turns_every_capability_on_and_says_so
   - test: tests/test_cli_access.py::test_the_api_listens_on_loopback_alone
   - test: tests/test_access.py::test_the_health_check_says_which_capabilities_are_on

2. The page opens on the visualiser alone, with the first-run hint and the
   transport below it, and the canvas names no mode yet. p5 and p5.sound come
   from the CDN, and run only if they are the bytes the lockfile installs.

   - spec: page loads and canvas is visible
   - spec: joe opens with the visualiser alone, the first-run hint and the transport below it
   - spec: Canvas mode badge is empty on initial load
   - spec: the Results window is closed on load
   - spec: the dock follows the window's size
   - spec: dismissing the first-run hint gives the dock its room
   - spec: each CDN script is held to the bytes of the p5 the lockfile installs
   - spec: p5 and p5.sound load from the CDN past their integrity check

3. **Joe, go!** starts the browser's audio. Until then **Live** is greyed.

   - spec: "Joe, go!" button is present and clickable
   - spec: Live button is disabled until Joe, go! is clicked
   - spec: a joe serving everything greys nothing, and Live opens once audio starts

4. A joe started with less shows it. Started as `uv run joe dev --allow media`,
   which serves the media API alone, the page greys **Library**, **Transcript** and
   **Live**, each tooltip naming the setting that turns it on. The Library and
   the transcript say what is off in a sentence with a link to
   [security.md](../security.md). The first-run hint keeps the steps that work,
   and says what `--allow` turns on. With no backend at all, nothing is greyed.

   - spec: a joe serving the media API alone greys Library, Transcript and Live, each naming its setting
   - spec: with no backend nothing is greyed: no backend is a normal way to run the page
   - spec: the Library and the transcript each say what is off, in a sentence with a link
   - spec: A library joe does not serve says so, and what turning it on exposes
   - spec: Fetch Latest is greyed while the library is off, and a refusal it meets anyway says so
   - spec: Live names only what its capture mode needs, and nothing once that is on
   - spec: the first-run hint keeps the steps that work and says what --allow turns on
   - spec: on a joe serving everything the first-run hint keeps all four steps
   - spec: the hint numbers the steps it keeps again, and names each flag once
   - test: tests/test_cli_access.py::test_dev_allow_media_serves_the_media_api_alone

## 2. Analyse a recording

1. Put a WAV or MP3 in `Data/Audio/` and open the **Library** (`L`). It lists
   the file, its name shown as text whatever it is called.

   - spec: the Library window closes on a second press of its button
   - spec: A file name is shown as text, never as markup

2. **Process** runs the pipeline on it. When the pipeline finishes, the
   Results window opens with the track and its note count, the piano roll
   draws its notes -- Raw white, Harmonic cyan, Percussive orange -- the canvas
   reads RESULTS, and the transport loads the recording.

   - spec: Library Process triggers pipeline and loads correct results
   - test: tests/test_api.py::test_run_on_file_runs_pipeline_for_file_inside_audio_dir

3. A file the pipeline cannot read says why in the Library. A pipeline that
   fails leaves the Results closed and loads no recording.

   - spec: Unsupported format shows error and keeps the Results window closed
   - spec: a pipeline failure opens no Results window and loads no recording

4. **Play** on a file loads it on the transport and plays it, its row
   highlighted, and the piano roll's playhead follows the scrubber. **×** beside
   the name ejects it. joe plays one recording at a time: Play, a recording
   stopping, and a pipeline finishing each make theirs the one.

   - spec: Library Play loads audio and highlights the active row
   - spec: Eject clears transport name, hides button, and removes library highlight
   - spec: the scrubber's knob clears the time readout at 1024 px
   - spec: the scrubber's knob clears the time readout at 1280 px
   - spec: the transport's groups lie side by side at 1024 px, with a take and its note showing
   - spec: the transport's groups lie side by side at 1280 px, with a take and its note showing

5. Or from a terminal, `uv run joe run` analyses every file in `Data/Audio/`;
   then **Results** (`A`) → **Fetch Latest** draws the newest result.

   - spec: the Results button opens the Results window
   - spec: Fetch Latest button loads results and shows note count
   - spec: the Results window closes on a second press of its button
   - spec: the panel's heading reads on one line, clear of its buttons

6. Or an earlier result, with no server needed: **Results** → **Load JSON** and
   a `Process_Data_*.json` from `Data/Output/`. A file that is not one says so,
   and a track named with markup is shown as text. The specs load a fixture of
   one, which carries the keys the page reads.

   - spec: Process_Data fixture has required backend contract keys
   - spec: the file input is inside the open Results window
   - spec: loading a valid JSON file renders the piano roll canvas
   - spec: piano roll canvas has non-zero dimensions after JSON load
   - spec: results meta shows note count after load
   - spec: Canvas mode badge shows RESULTS after loading notes from file input
   - spec: malformed JSON shows load-error element and does not crash
   - spec: A track named with markup is shown as text

7. `←` and `→` step through the setlist: the era panel at the top of the
   visualiser shows its genre, title, composer and year.

   - spec: arrow key navigation updates era panel and does not crash
   - spec: era panel shows correct genre after first ArrowRight
   - spec: era panel genre updates on second ArrowRight
   - spec: era panel clamps at index 0 on repeated ArrowLeft

## 3. Record live

1. Choose where **Live** records from: **Browser mic**, this browser's
   microphone, whose take is sent to joe's library; or **joe's mic**, the
   microphone of the machine joe runs on, which needs joe's microphone setting
   as well as its library.

   - spec: the capture select says where Live records from, and what each choice is
   - test: tests/test_audio_upload.py::test_an_upload_enters_the_library_whole

   No test drives joe's mic: `POST /api/capture/start` and `/stop` have none.

2. **Joe, go!**, then **Live**. The dot pulses, the canvas reads LIVE, and
   onsets scroll across the piano roll as the instrument plays. **Stop** keeps the take in
   `Data/Audio/` and loads it on the transport, where the scrubber steps
   through the notes the live layer froze.

3. **Library → Process** on the new file analyses it as in 2.2, and Play
   replays it with its notes.

   No spec or test drives steps 2 and 3: a live recording needs a microphone,
   and none is scripted.

## 4. Arrange the windows

1. ♫ **Library**, ▤ **Results** and ¶ **Transcript**, or `L`, `A` and `T`, open a
   window beside the visualiser, and the piano roll narrows to make room. A
   second joins the first as a tab of its stack. A window's button or key brings
   it to the front when another tab is over it, and closes it when it is in
   front. `Esc` closes the Library, the Results and the Transcript. Keys typed
   into a field open nothing.

   - spec: the window buttons are icons, each named for its window and its key
   - spec: L opens and closes the Library, and A the analysis Results
   - spec: a panel opens as a window beside the visualiser, and the piano roll narrows to make room
   - spec: a second panel joins the first one as a tab of its stack, in front
   - spec: a button brings its window to the front when another tab is over it, rather than closing it
   - spec: a window's button or key closes it when it is in front, and the visualiser fills the dock again
   - spec: Esc closes whatever is open, and opens nothing that was closed
   - spec: keys typed into a field open nothing

2. A tab's ✕, or `Delete` on a focused tab, closes its window; what the window
   held is there when it opens again. The visualiser cannot be closed. Every
   window's tab names it, and none pops out of the page.

   - spec: a tab's ✕ closes its window, and what the window held is there when it opens again
   - spec: a closed window's panel waits in the page, hidden, so what reaches for it still finds it
   - spec: a window that can be closed closes by Delete on its tab
   - spec: the visualiser cannot be closed: its tab has no ✕, and Delete on it leaves it
   - spec: every window carries its id, its tab names it, and none of them pops out

3. The **Panels** menu (▦) lists every window and says which are closed; one
   chosen opens. It works by keyboard, and `Escape` there closes the menu and
   nothing else.

   - spec: the Panels menu lists every window, says which are closed, and opens one
   - spec: the Panels menu by keyboard: arrows move, and Escape closes the menu and leaves the windows
   - spec: a click outside the Panels menu closes it

4. The arrangement is kept across a reload. **Panels → Reset layout** puts back
   the visualiser alone. A kept arrangement this page cannot use is dropped for
   the default, and a note at the top of the page says why.

   - spec: the arrangement is kept across a reload, and Reset layout puts back the visualiser alone
   - spec: a saved arrangement that is not JSON is dropped for the default, and the page says why
   - spec: a saved arrangement that names a window this version lacks is dropped for the default, and the page says why
   - spec: a saved arrangement that has no visualiser is dropped for the default, and the page says why
   - spec: a saved arrangement that shows a window twice is dropped for the default, and the page says why
   - spec: a saved arrangement that GoldenLayout refuses is dropped for the default, and the page says why
   - spec: readSavedLayout: nothing saved, a layout to load, or why it cannot be
