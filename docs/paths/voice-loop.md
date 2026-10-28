# The voice loop

A person talking with [qmcp](https://github.com/quaternionmedia/qmcp) through
joe, with nothing typed after two commands -- joe listens and transcribes, qmcp
records, asks consent and has its local model answer -- and reading back what
was heard. qmcp's `docs/voice-loop-demo.md` is the loop's own onboarding, and
`GET /api/voice/conversation` in [api.md](../api.md) is the stream the page
reads.

Run this lane's specs:

```bash
npx playwright test --grep @voice-loop
```

## 1. Set up the microphone, once

1. `uv run joe voice setup`, and keep talking when it says so. It saves the
   microphone that recorded a test sentence, and every recording uses it. A
   saved microphone that is not connected is named when the default input
   stands in for it, and in a failure on that default.

   - test: tests/test_cli_voice_setup.py::test_setup_falls_through_to_the_next_entry_when_the_proof_cannot_record
   - test: tests/test_cli_voice_setup.py::test_recording_uses_the_saved_device_unless_the_environment_names_one
   - test: tests/test_cli_voice_setup.py::test_recording_on_the_default_in_place_of_a_gone_microphone_says_so
   - test: tests/test_cli_voice_setup.py::test_a_failure_on_the_default_names_the_saved_microphone_it_stood_in_for

## 2. Start the conversation

1. Start joe, `uv run joe dev`, and in qmcp's checkout
   `uv run qmcp serve --converse --runtime local`. Either may start first; the
   conversation waits for the other.

2. qmcp says *"Ready. What should be done?"* and the Voice window opens, in a
   stack of its own above the transcript when the transcript is open. Until a
   conversation starts the Voice window stays closed, and **Instruct by voice**
   is at hand in the transport. A tab put in front of the Voice window stays in
   front. A Voice window opened from the Panels menu stays open, and a reload
   brings it back; one the conversation opened closes once the exchange is over
   and nothing in it waits, and a reload does not bring it back.

   - spec: the Voice window stays closed until a conversation starts
   - spec: a Voice window opened from the Panels menu stays open while no conversation runs
   - spec: the button is at hand while the Voice window is closed
   - spec: a conversation opens the Voice window above the transcript, so both can be read
   - spec: a conversation leaves a tab the person put in front of the Voice window where it is
   - spec: a Voice window opened from the Panels menu is brought back by a reload
   - spec: a Voice window the conversation opened is not brought back by a reload, and opens again in its own colour
   - spec: a Voice window the conversation opened is the person's once they open it themselves

## 3. Take a turn

1. The Voice window shows each turn as it happens: the question asked with the
   microphone closed, the open microphone, the speech, the pause, the
   transcription, what was heard and what was recorded. Every state has a label
   and a colour of its own. A question asked again says why, and the
   microphone's level shows only while it is open.

   - spec: a whole exchange reads in order, ending on what was recorded
   - spec: every state looks different from every other
   - spec: a conversation's first state shows in its own colour at once, not faded in from another
   - spec: a re-ask says why it is asking again
   - spec: the microphone level shows only while the microphone is open
   - test: tests/test_conversation.py::test_the_stream_replays_the_backlog_then_the_level

2. Say an instruction that names a project -- "Which file in qmcp says what qmcp
   is?" -- and it is read back. Heard confidently, a moment of silence agrees;
   otherwise say "agree", or "again" to say it once more. Then "approve" to the
   consent.

3. The take is written as it is spoken, a struck word crossed out and a segment
   still being read marked. Clicking a word strikes it, and `Backspace` strikes
   the last word standing, unless the focus is in a field.

   - spec: the take shows as it is written, a struck word crossed out and a pending segment marked
   - spec: clicking a word strikes it, and Backspace strikes the last one standing
   - spec: Backspace typed into a field strikes nothing

4. Or answer without speaking: a question's options are numbered buttons, and
   with the page focused `1`–`9` answer by position, `R` asks for it again,
   `Shift`+`Esc` stops listening, and `~`, held, keeps the turn open through
   pauses. A key or button counts as having said the word.

   - spec: a question offers its options as numbered buttons, and a click answers
   - spec: the number keys answer by position, R repeats and Shift+Esc stops
   - spec: R still asks the voice loop to say it again, and opens neither the Library nor the Results
   - spec: holding the tilde key holds the turn open until it is released
   - spec: keys typed into a field are not answers
   - spec: the options go once the exchange has an outcome, and an answer by key is marked
   - spec: a window losing focus releases a held key, once, and sends nothing when none is held
   - spec: a question said again on request says so

5. The answer is said back, then *"Anything else?"*: "yes" for another, "no" to
   leave it listening, "stop listening" to end it. Every take is kept in
   `Data/Voice/` as `capture_<time>.wav`; nothing deletes them.

## 4. Read back what was heard

1. `T`, or **Transcript**, opens the whole exchange, oldest first: each question
   as it was asked and each take as it was heard, its struck words crossed out,
   how sure the transcriber was, and how it was labelled. It is read from joe's
   datapoints, so a reload keeps it, and it is extended live, following the
   newest line unless scrolled back.

   - spec: T opens the whole transcript, oldest first, with strikes, confidence and labels
   - spec: opening the transcript shows its newest line
   - spec: the pane closes with ×, opens from the transport, and is remembered across a reload
   - spec: what is asked and the take being written arrive live
   - spec: a history that arrives after the stream keeps what streamed in
   - spec: T typed into a field opens nothing
   - spec: the first-run hint sits below the pane, not over its last lines
   - test: tests/test_history.py::test_the_history_route_serves_the_transcript_within_its_bounds

2. A long exchange stays readable: takes in a row that heard nothing fold into
   one line, a question over 240 characters shows three lines until opened, and
   a line names each day where it changes.

   - spec: takes in a row that heard nothing fold into one line, which opens and stays open
   - spec: a long question shows three lines until opened, and stays open
   - spec: the transcript names each day where it changes: today, yesterday, then the date
   - spec: a day this year is named without its year, and one in another year with it

3. **What can be said** lists the words the conversation and its checks listen
   for, and joe's own, which are listed with no conversation running.

   - spec: what can be said lists the conversation, its checks and joe
   - spec: without the conversation running, joe's words are still listed

4. **Show** on a heard take puts it on the visualiser: its recording on the
   transport, played from the start, and its words along the bottom of the piano
   roll at the times they were said, a struck word dimmed and crossed out. The
   word under the playhead is lit, and follows the recording as it plays or is
   scrubbed. A word too long for its place ends in an ellipsis and shows whole
   under the pointer. A take whose recording was not kept is laid out, and the
   transport stays stopped and says "recording not kept". A take kept before
   joe's voice folder moved is found by its recording's file name.

   - spec: Show puts the take on the transport and its standing words on the timeline
   - spec: words share their segment evenly and a struck one keeps its place
   - spec: the lit word is the one under the playhead, and a struck word is never lit
   - spec: while the take plays, the lit word follows it word by word
   - spec: a standing word is lit from its start up to its end
   - spec: a word too long for its place is cut and ends in an ellipsis
   - spec: a clipped word is shown whole under the pointer, and a word that fits is not
   - spec: a take whose recording is not kept is laid out, and the transport stays stopped and says so
   - spec: ejecting the recording takes its words off the timeline
   - test: tests/test_take_audio.py::test_a_take_s_recording_is_served_by_its_id
   - test: tests/test_take_audio.py::test_a_record_naming_where_the_voice_folder_was_is_found_by_its_file_name

## 5. Instruct by voice, and answer qmcp's queue

1. With qmcp started without `--converse`, **Instruct by voice** takes one
   instruction aloud into qmcp's inbox, follows the run to its end, and shows
   what was recorded and for which project. While a conversation runs it says
   so, rather than opening the microphone a second time.

   - spec: instructing posts once, waits for the run, then shows what was recorded
   - spec: an instruction that named no project is shown as such, unresolved
   - spec: a run that ends with the inbox empty says so
   - spec: a second conversation that fails does not show the first one's row
   - spec: a run that fails shows the command's own last words, not the inbox
   - spec: a refusal of the instruction shows qmcp's reason
   - spec: a qmcp without the inbox gets a note, and the page goes on
   - spec: a qmcp that cannot be reached is said so

2. qmcp's oldest waiting request is offered in the Voice window with its
   options, and **Answer by voice** answers it aloud, follows the run, and reads
   the queue again.

   - spec: nothing waiting leaves the Voice window closed
   - spec: the oldest waiting request is offered with its options
   - spec: answering asks qmcp once, waits for the run, then reads the queue again
   - spec: a run that fails shows the command's own last words
   - spec: a refusal of the answer shows qmcp's reason
   - spec: the outcome stepping aside leaves the panel to the queue

3. While qmcp cannot be reached, **Instruct by voice** is dimmed and its tooltip
   says how to start it, and a page that is hidden asks qmcp nothing.

   - spec: while qmcp cannot be reached, Instruct by voice says so, and a hidden page asks nothing
   - spec: once qmcp answers, Instruct by voice is itself again
