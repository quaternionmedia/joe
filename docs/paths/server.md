# joe as a server

A program using joe over HTTP: a video editor, alfred, through the media API;
voice tools, vox and qmcp, through the voice routes; and scripts through the
library's. joe has no authentication -- what it serves, it serves to anything
that reaches its port -- so each part is a setting, and
[security.md](../security.md) says what each one exposes.
[api.md](../api.md) and [media.md](../media.md) have every route and field.

This lane's checks are Python tests, run with the suite:

```bash
uv run pytest tests/
```

## 1. Start joe as a server

1. `uv run joe backend` serves the media API alone, listening on `127.0.0.1`,
   and says as it starts that it has no authentication and what is on.
   `--allow` names what else to serve -- `library`, `microphone`,
   `transcripts`, `media`, or `all` -- as do the settings
   `JOE_ALLOW_<NAME>=1`. A name that is no capability starts nothing, and a
   setting joe cannot read stops it.

   - test: tests/test_cli_access.py::test_each_allow_turns_its_capability_on_for_the_api
   - test: tests/test_cli_access.py::test_allow_all_turns_every_one_on
   - test: tests/test_cli_access.py::test_a_name_that_is_no_capability_starts_nothing
   - test: tests/test_access.py::test_the_banner_says_there_is_no_authentication_and_what_is_on
   - test: tests/test_access.py::test_the_server_will_not_start_on_a_setting_it_cannot_read

2. `GET /api/health` says which capabilities are on. A route whose capability
   is off answers `403`, naming the setting that turns it on, before it does
   anything it was asked. The vocabulary is always served, and the media API
   unless `JOE_ALLOW_MEDIA=0` turns it off.

   - test: tests/test_access.py::test_the_health_check_says_which_capabilities_are_on
   - test: tests/test_access.py::test_a_fresh_joe_serves_the_media_api_and_nothing_else
   - test: tests/test_access.py::test_a_capability_that_is_off_answers_403_naming_its_setting
   - test: tests/test_access.py::test_a_refusal_comes_before_anything_the_route_was_asked
   - test: tests/test_access.py::test_every_route_belongs_to_the_capability_this_table_says
   - test: tests/test_access.py::test_the_vocabulary_is_always_served

## 2. Caption and analyse a video for an editor

What joe hears in a clip, for alfred: the words with their times, for captions,
and its beats, loudness, silences and waveform, for cutting.

1. Put ffmpeg on `PATH`, or name it in `JOE_FFMPEG`. Start the API alone on a
   port alfred does not use -- alfred has 8000 -- and check that joe answers
   there:

   ```powershell
   uv run uvicorn api:app --port 8010
   curl http://localhost:8010/openapi.json   # "title": "Joe API"
   ```

   - test: tests/test_media_api.py::test_no_ffmpeg_is_503_and_says_how_to_name_one

2. Upload the clip, and ask about it from then on by the answer's `media_id`:

   ```bash
   curl -X POST http://localhost:8010/api/media \
     -H "Content-Type: video/mp4" --data-binary @clip.mp4
   # {"media_id": "323be26e5105eb0a57ca72d44566409b", "duration": 2.005,
   #  "sample_rate": 48000, "channels": 1, "has_audio": true}
   ```

   A clip with no sound track is refused with a `422`, not kept, and one over the
   size cap (`JOE_MEDIA_MAX_BYTES`) with a `413` as it arrives.

   - test: tests/test_media_api.py::test_every_audio_and_video_type_is_taken_and_its_sound_kept_three_ways
   - test: tests/test_media_api.py::test_a_video_with_no_sound_track_is_422
   - test: tests/test_media_api.py::test_a_body_larger_than_the_cap_is_413_while_it_arrives

3. Ask for the words with their times, and for what the sound does. Every time
   in the answers is a time in the clip.

   ```bash
   curl -X POST "http://localhost:8010/api/media/323be26e5105eb0a57ca72d44566409b/transcribe"
   curl -X POST "http://localhost:8010/api/media/323be26e5105eb0a57ca72d44566409b/analyze?features=beats,loudness,silence"
   ```

   - test: tests/test_media_transcribe.py::test_a_transcript_has_segment_and_word_times_in_v1_s_shape
   - test: tests/test_media_api.py::test_an_analysis_answers_every_feature_in_v1_s_shape
   - test: tests/test_media_api.py::test_only_the_features_asked_for_are_answered
   - test: tests/test_media_api.py::test_a_track_that_starts_late_is_kept_on_the_media_s_own_time

4. Delete it when done, or leave it: an upload goes an hour after its last use
   (`JOE_MEDIA_TTL`).

   ```bash
   curl -X DELETE http://localhost:8010/api/media/323be26e5105eb0a57ca72d44566409b
   ```

   - test: tests/test_media_api.py::test_delete_removes_the_upload_and_its_files
   - test: tests/test_media_api.py::test_an_upload_expires_an_hour_after_its_last_use_and_is_swept

## 3. Put a recording in the library and run the pipeline

Needs `--allow library` (`JOE_ALLOW_LIBRARY=1`).

```bash
curl -X POST http://localhost:8000/api/audio/upload \
  -H "Content-Type: audio/wav" --data-binary @my_recording.wav
# {"filename": "capture_20240101_120000_000000.wav"}
curl -X POST http://localhost:8000/api/run/capture_20240101_120000_000000.wav
curl http://localhost:8000/api/results/latest
```

No test reads `GET /api/results/latest`.

- test: tests/test_audio_upload.py::test_an_upload_enters_the_library_whole
- test: tests/test_api.py::test_run_on_file_runs_pipeline_for_file_inside_audio_dir

- test: tests/test_audio_upload.py::test_a_type_joe_does_not_take_is_refused_before_its_length
- test: tests/test_audio_upload.py::test_a_declared_length_over_the_cap_is_refused_before_a_byte_is_read
- test: tests/test_api.py::test_run_on_file_rejects_non_bare_names
- test: tests/test_access.py::test_nothing_is_written_to_the_library_while_it_is_off

## 4. Hear and transcribe for a voice tool

1. `POST /api/voice/listen` records a take from joe's microphone and answers
   what was heard (`microphone`). With no microphone it answers `503`. A hint
   is handed to the transcriber, within its bound, and what the microphone
   reports is published to the conversation stream.

   - test: tests/test_api_voice.py::test_voice_listen_refuses_a_hint_longer_than_its_bound
   - test: tests/test_api_voice.py::test_voice_listen_returns_503_when_no_microphone
   - test: tests/test_api_voice.py::test_voice_listen_hands_the_hint_to_the_transcriber
   - test: tests/test_conversation.py::test_the_listen_route_publishes_what_the_microphone_reports

2. `POST /api/voice/transcribe?filename=` transcribes a file already in joe's
   folders by its name (`library`), looking in `Data/Voice/` before
   `Data/Audio/`: `vox loop` writes `said.wav` and `echo.wav` to `Data/Voice/`
   and asks for them by name. No test calls the route itself; these check the
   look-up it makes.

   - test: tests/test_api.py::test_a_name_in_both_folders_is_the_voice_folders
   - test: tests/test_api.py::test_resolve_audio_path_rejects_non_bare_names

3. A conversation run by another program posts its states to
   `POST /api/voice/conversation` (`microphone`), and the page reads them from
   `GET /api/voice/conversation` (`transcripts`), a stream that resumes after
   the last event a reader saw. What was said and heard is kept, and
   `GET /api/voice/history` serves it; a take's recording is served by its id,
   from joe's own voice folder only.

   - test: tests/test_conversation.py::test_the_dialog_posts_its_own_states
   - test: tests/test_conversation.py::test_the_stream_resumes_after_the_last_event_the_client_saw
   - test: tests/test_history.py::test_a_sentence_said_is_written_from_the_conversation_route
   - test: tests/test_take_audio.py::test_a_recording_outside_joe_s_voice_folder_is_never_served
