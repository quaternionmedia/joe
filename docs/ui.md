# joe's page

The page joe serves at `http://localhost:3000/joe/` (`uv run joe dev`): a dock
of windows, and below it the first-run hint and the transport.

## The window

**The dock.** The visualiser and every panel are windows of one GoldenLayout
(`src/layout/`). The first-run hint and the transport sit below the dock, not in
it, so nothing is drawn over the piano roll's last lines.

**The default arrangement** is the visualiser alone. A window opens beside it:
Library, Results and Transcript as tabs of one stack, in a column to the right
of the visualiser; Voice in a stack of its own above them, so a conversation and
its transcript are both on screen.

**Opening and closing.** The transport's window buttons -- ♫ **Library**, ▤
**Results** and ¶ **Transcript**, each named in its tooltip -- or `L`, `A` and
`T`, each open their window, bring it to the front when another tab is over it,
and close it when it is in front. `Esc` closes the Library, the Results and the
Transcript. The **Panels** menu (▦, after those buttons) lists every window,
marks the closed ones, opens the one chosen, and resets the layout.

**Windows that come forward.** Results opens when the pipeline finishes
(**Library → Process**). Voice opens when a conversation starts, unless it is
open already: a tab put in front of it stays in front. A Voice window the
conversation opened closes once the exchange is over and nothing in it is
waiting; one opened from the Panels menu stays.

**Arranging.** A tab dragged to another stack joins it, and dragged to an edge
splits it; a splitter between windows resizes them; **Maximise** gives a stack
the dock. A tab's ✕, or `Delete` on a focused tab, closes its window; so do the
Library's and the Transcript's own × in their headers. With a tab
focused, `Enter` or `Space` shows it, and the arrow keys, `Home` and `End` move
along its stack's tabs. The visualiser cannot be closed.

**The first-run hint** above the transport names the first steps; its ×
dismisses it for good in this browser (`joe-hint-dismissed`), and the dock takes
its room.

**The saved arrangement** is kept in this browser's localStorage under
`joe.layout.v1`, a quarter of a second after a change and as the page goes. It
is read before the dock is built: one that is not JSON, names a window this
version does not have, shows a window twice or not under its id, has windows
popped out, or has no visualiser is dropped for the default, and a note at the
top of the page says why. **Reset layout** forgets it. A Voice window the
conversation opened is left out of it, so a reload does not bring it back
empty; one the person opened from the Panels menu is kept.

## Windows

### Visualiser

Id `visualiser`. The spectrum the microphone or the playing file draws, the
piano roll over it -- live notes while recording, the pipeline's notes once
loaded -- and the era panel at the top. A take shown from the transcript lays
its words along the bottom, the word under the playhead lit. It cannot be
closed, and its canvases take the window's size.

### Library

Id `library`. The recordings in `Data/Audio/`, each with **Play** and
**Process**, **Refresh** to read them again, and why a file could not be
processed. While joe's library is off it says so, with a link to
[security.md](security.md).

### Results

Id `results`. What the pipeline found: **Fetch Latest** and **Load JSON**, the
track, its note count, and the legend of the piano roll's colours.

### Transcript

Id `transcript`. The whole spoken exchange, oldest first: each question as it
was asked and each take as it was heard, its struck words crossed out, with how
sure the transcriber was and how it was labelled, and **Show** to put a take on
the visualiser. **What can be said** lists the words the conversation and joe
listen for.

### Voice

Id `voice`. The conversation as it goes: whose turn it is, the microphone's
level, the take being written, the question's options as buttons, **Repeat**
(`R`), **Stop** (`Shift`+`Esc`) and the held `~` that keeps the turn open,
qmcp's queue, and what **Instruct by voice** recorded.

## What the window does not have

- **No popouts.** Each window holds an element of this page, and a window of its
  own would open empty.
- **No second copy of a window.** Opening one that is open brings it to the
  front.
