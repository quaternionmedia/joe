# Manual test plan

What the automated checks cannot reach: a real microphone, a real voice, and a
person hearing the tones. Everything else about these paths is asserted by a
test that drives a scripted stream or a mocked route; this page is for the
part between the hardware and that stream. Each section names the automated
check that stands nearest it, so a failure here says which seam broke.

Run it before a version tag, on the machine the tag will be used on, with
`uv run joe dev` running and the page open at `http://localhost:3000/joe`.
Record the date, the commit, the microphone and the output device beside the
result.

## 1. The microphone is found and heard

1. `uv run joe voice setup`, and keep talking when it says so.
2. Expect it to pick the input that heard you, save it to
   `Data/voice-device.json`, and print a transcription of the test sentence
   that is recognisably what you said.
3. `uv run joe voice devices`: the saved input is marked `S`.

Nearest automated check: `tests/test_cli_voice_setup.py` and
`tests/test_voice_devices.py`, against a stand-in device list.

## 2. A take is written as it is spoken

1. With the voice panel showing, start a turn (**Answer by voice** on a waiting
   qmcp request, or `uv run joe voice listen` in a terminal).
2. Say a sentence with a half-second pause in it.
3. Expect the words of the first half on the panel before you finish the
   second, and the take's text, when it ends, to be the words shown.
4. Say "scratch that" as a segment of its own: the segment before it is
   struck on the panel and missing from the take's text.

Nearest automated check: `tests/test_transcript.py` and
`tests/e2e/voice-transcript.spec.js`, against a scripted stream and a stand-in
transcriber.

## 3. Keys and the held talk key

1. During a question with options, press `1`: the turn ends at once with that
   option as its answer.
2. Hold `~` through a pause of several seconds and release: the take does not
   end during the pause, and ends on release.
3. `Shift`+`Esc` stops listening.

Nearest automated check: `tests/test_control.py` and
`tests/e2e/voice-keys.spec.js`.

## 4. The tones are heard, and are not recorded

1. With `JOE_CUES` unset, answer a question by voice.
2. Expect two rising notes just before the microphone opens and one lower note
   once the take has ended, on the output `JOE_OUTPUT_DEVICE` (or
   `VOX_OUTPUT_DEVICE`) names, else the default.
3. Play the take back from the transcript pane (**Show**): the rising notes
   are not in the recording.

Nearest automated check: `tests/test_control.py` checks when a cue is asked
for; nothing automated listens to one.

## 5. Speaking over a question interrupts it

1. Through speakers, have qmcp ask a question, and answer clearly louder than
   it before it finishes.
2. Expect the question to stop within about a second and the take to keep
   your answer from its first word.
3. Repeat at roughly the question's own loudness: expect it not to stop.

Nearest automated check: `tests/test_watch.py`, against scripted levels.

## 6. One recording, end to end

1. Click **Joe, go!**, choose **Browser**, click **Live**, play or sing a few
   notes, and click **Live** again.
2. Expect the recording in **Library**; **Process** it and expect the piano
   roll to switch to **RESULTS** with notes drawn.

Nearest automated check: `walkthrough/03-in-the-browser.md` runs the same
**Library → Process** path on a synthesised recording uploaded through the
API; only the browser's own capture of a microphone is left to this step.
