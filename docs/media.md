# joe's media API

joe is the audio engine of a video pipeline: a video editor (alfred) sends it a
clip, or the mixed sound of a timeline, and asks what is said in it and when
(captions), and how it moves -- tempo, beats, onsets, loudness, silences and a
waveform. The routes live under `/api/media`, beside the voice API and
independent of it. Nothing here changes `/api/audio/upload` or
`/api/voice/transcribe`.

An upload is answered with an id; everything after is asked by that id:

```text
POST   /api/media                        -> 201 {"media_id", "duration", "sample_rate", "channels", "has_audio"}
POST   /api/media/{media_id}/transcribe  -> {"text", "language", "segments", "info"}
POST   /api/media/{media_id}/analyze     -> {"duration", "tempo", "beats", "onsets", "loudness", "silences", "peaks"}
DELETE /api/media/{media_id}             -> 204
GET    /api/media/capabilities           -> {"formats", "features", "speech_model", "word_timestamps", ...}
```

Every time joe answers is in seconds of the uploaded media. Every failure is
`{"detail": str}` -- a sentence, never a list.

## Running it beside alfred

joe's CLI serves the API on port 8000, which is alfred's. Run the API alone on
another port, from this checkout:

```powershell
uv run uvicorn api:app --port 8010
```

and point alfred at `http://host.docker.internal:8010` (from its containers) or
`http://localhost:8010`. `curl http://localhost:8010/openapi.json` names the
server -- `Joe API` -- before you trust an answer from that port.

**ffmpeg is required.** joe decodes uploads with it, and measures LUFS with its
`ebur128` filter. It is `JOE_FFMPEG` when set (a path to the binary), else
`ffmpeg` on PATH. Without one, `GET /api/media/capabilities` lists no formats
and an upload is a 503. On Windows any build will do -- one that comes with an
editor such as Kdenlive (`C:\Program Files\kdenlive\bin\ffmpeg.exe`) works.

**The speech model** is whisper `base`, the voice loop's own size, loaded from
whisper's cache (`~/.cache/whisper/base.pt`; downloaded once if missing) the
first time something is transcribed. That first transcription also compiles
whisper's word-timing code: on the machine these examples come from, four
seconds of speech took eighteen seconds the first time and three after.

### Settings

| Variable | Default | What it sets |
| --- | --- | --- |
| `JOE_FFMPEG` | `ffmpeg` on PATH | The ffmpeg binary |
| `JOE_MEDIA_DIR` | `Data/Media/` in this checkout | Where uploads are kept |
| `JOE_MEDIA_TTL` | `3600` | Seconds an upload is kept after its last use |
| `JOE_MEDIA_MAX_BYTES` | `1073741824` (1 GiB) | The largest upload taken |
| `JOE_MEDIA_MAX_SECONDS` | `7200` (two hours) | The longest sound taken |

## Uploads are private and kept for a while

Each upload is a directory under `JOE_MEDIA_DIR`, named by a random 128-bit id
that is the only way to reach it -- no route lists uploads. ffmpeg decodes the
first audio stream once into three WAVs: the sound at its own rate and channel
count (levels, silences, peaks), 16 kHz mono (whisper) and 22050 Hz mono
(librosa's beat tracker). The upload itself is deleted as soon as its sound is
out. Nothing is loudness-normalised: "normalised" means one format, never one
level. A sound track that starts after its video does is padded with silence
to its start, so its times are the video's.

An upload is kept `JOE_MEDIA_TTL` seconds after it was last used -- uploaded,
transcribed or analysed -- and then removed by a sweep the server runs while it
is up, and at every upload; asking for it after that is a 404. `DELETE` removes
it at once. An upload being transcribed or analysed is never swept, and one
deleted meanwhile goes when that ends.

**ffmpeg opens only media.** It may open an upload only with the demuxers of
the formats below, and only as a local file: a playlist or a concat script
sent as "audio" could otherwise read other files on this machine into the
sound joe returns.

---

## `GET /api/media/capabilities`

What this engine takes and does. Check it before sending: the limits are here.

```bash
curl http://localhost:8010/api/media/capabilities
```

```json
{
  "formats": ["audio/aac", "audio/flac", "audio/m4a", "audio/mp3", "audio/mp4", "audio/mpeg",
              "audio/ogg", "audio/vnd.wave", "audio/wav", "audio/wave", "audio/webm", "audio/x-aac",
              "audio/x-flac", "audio/x-m4a", "audio/x-wav", "video/matroska", "video/mp4",
              "video/quicktime", "video/webm", "video/x-matroska"],
  "features": ["tempo", "beats", "onsets", "loudness", "silence", "peaks"],
  "speech_model": "whisper-base",
  "word_timestamps": true,
  "max_bytes": 1073741824,
  "max_seconds": 7200.0,
  "ttl_seconds": 3600.0
}
```

`formats` is every `Content-Type` an upload may have, and is empty when there
is no ffmpeg. `max_bytes`, `max_seconds` and `ttl_seconds` are the settings
above.

## `POST /api/media`

The file as the raw request body, its type in `Content-Type`:

| Kind | Content types |
| --- | --- |
| wav | `audio/wav`, `audio/x-wav`, `audio/wave`, `audio/vnd.wave` |
| mp3 | `audio/mpeg`, `audio/mp3` |
| ogg | `audio/ogg` |
| flac | `audio/flac`, `audio/x-flac` |
| m4a / aac | `audio/mp4`, `audio/m4a`, `audio/x-m4a`, `audio/aac`, `audio/x-aac` |
| webm audio | `audio/webm` |
| mp4 | `video/mp4` |
| mov | `video/quicktime` |
| webm video | `video/webm` |
| mkv | `video/x-matroska`, `video/matroska` |

Parameters (`; codecs=opus`) and case are ignored.

```bash
curl -X POST http://localhost:8010/api/media \
  -H "Content-Type: video/mp4" --data-binary @clip.mp4
```

**`201 Created`**

```json
{"media_id": "323be26e5105eb0a57ca72d44566409b", "duration": 2.005, "sample_rate": 48000, "channels": 1, "has_audio": true}
```

`duration` is the sound's, in seconds to the millisecond; `sample_rate` and
`channels` are the source's own. `has_audio` is `true` in every 201: a file
with no audio is refused, not kept.

**Errors**

| Status | When | `detail`, for example |
| --- | --- | --- |
| `415` | The `Content-Type` is none of the above, or missing | `unsupported media type 'text/plain'; joe takes audio/aac, ...` |
| `413` | The body is over `JOE_MEDIA_MAX_BYTES` -- judged on `Content-Length` before a byte is read, and counted as it arrives otherwise | `media larger than 1073741824 bytes (JOE_MEDIA_MAX_BYTES)` |
| `413` | The sound is longer than `JOE_MEDIA_MAX_SECONDS` | `this media's sound is longer than 7200 seconds (JOE_MEDIA_MAX_SECONDS)` |
| `422` | No audio stream -- a video with no sound track | `this media has no audio stream` |
| `422` | Nothing ffmpeg can decode | `this media has no audio ffmpeg can decode: Error opening input files: Invalid data found when processing input` |
| `503` | No ffmpeg | `ffmpeg was not found: set JOE_FFMPEG to its path or put it on PATH` |

A 413 judged on `Content-Length` is answered while the client may still be
sending; a client that checks `max_bytes` first never meets it.

## `POST /api/media/{media_id}/transcribe`

What is said, with segment and word times.

| Query | Default | |
| --- | --- | --- |
| `language` | none | A code (`en`) or a name (`English`). Absent or empty, whisper detects it from the first thirty seconds |
| `words` | `true` | Word timestamps; `false` leaves each segment's `words` empty |

```bash
curl -X POST "http://localhost:8010/api/media/278fe25bbd08c0ccaff9caa7b4184d10/transcribe?language=&words=true"
```

**`200 OK`** -- four seconds of speech:

```json
{
  "text": "Captions come from Joe. Every word has its time.",
  "language": "en",
  "segments": [
    {"start": 0.0, "end": 3.46, "text": "Captions come from Joe. Every word has its time.",
     "words": [
       {"start": 0.0, "end": 0.56, "word": " Captions", "probability": 0.9311},
       {"start": 0.56, "end": 0.76, "word": " come", "probability": 0.9851},
       {"start": 0.76, "end": 1.04, "word": " from", "probability": 0.9991},
       {"start": 1.04, "end": 1.28, "word": " Joe.", "probability": 0.5505},
       {"start": 1.92, "end": 2.48, "word": " Every", "probability": 0.9563},
       {"start": 2.48, "end": 2.7, "word": " word", "probability": 0.9965},
       {"start": 2.7, "end": 2.94, "word": " has", "probability": 0.9981},
       {"start": 2.94, "end": 3.14, "word": " its", "probability": 0.9256},
       {"start": 3.14, "end": 3.46, "word": " time.", "probability": 0.9966}
     ]}
  ],
  "info": {"model": "whisper-base", "language": null, "words": true, "duration": 4.349,
           "avg_logprob": -0.3965, "no_speech_prob": 0.0134, "compression_ratio": 0.8571}
}
```

- `language` is the language transcribed: the one given, or whisper's guess.
  `info.language` is the one asked for, `null` when it was left to detection.
- A segment's `text` is trimmed. Its `words` are whisper's own, leading space
  and punctuation included, so they join back into the segment's text in any
  language -- `"".join(words).strip() == text`.
- Times are rounded to the millisecond, probabilities to four places.
- `info` carries whisper's own confidence: the mean `avg_logprob` and the
  largest `no_speech_prob` and `compression_ratio` over the segments.

Transcriptions take turns on a whisper model of the media API's own -- never
the voice loop's, so a conversation is not kept waiting behind captions -- and
a request waits its turn. An hour of speech takes minutes on a CPU; give the
client's timeout room.

**Errors:** `404` for an id that is not here; `422` for a `language` whisper
does not know (`unknown language 'klingon'; give a code such as 'en' or a name
such as 'English'`) or a `words` that is not a boolean
(`words: Input should be a valid boolean, unable to interpret input`).

## `POST /api/media/{media_id}/analyze`

| Query | Default | |
| --- | --- | --- |
| `features` | all six | Comma-separated: `tempo`, `beats`, `onsets`, `loudness`, `silence`, `peaks` |
| `peaks_rate` | `50` | Waveform values per second, `1..1000` |
| `silence_db` | `-40` | The level, in dBFS, a silence stays under, `-120..0` |
| `silence_min` | `0.5` | The shortest silence reported, in seconds, `0 < s <= 3600` |

```bash
curl -X POST "http://localhost:8010/api/media/f934079ba002a614c6a0e6d710ca124f/analyze?features=tempo,beats,onsets,loudness,silence,peaks&peaks_rate=2"
```

**`200 OK`** -- ten seconds of a click track at 120 BPM, its first click at 0.5 s:

```json
{
  "duration": 10.0,
  "tempo": 120.19,
  "beats": [0.511, 1.01, 1.509, 2.009, 2.508, 3.007, 3.506, 4.005, 4.516, 5.016, 5.515, 6.014,
            6.513, 7.012, 7.512, 8.011, 8.51, 9.009, 9.509],
  "onsets": [0.511, 1.01, 1.509, 2.009, 2.508, 3.007, 3.506, 4.005, 4.505, 5.004, 5.503, 6.002,
             6.502, 7.012, 7.512, 8.011, 8.51, 9.009, 9.509],
  "loudness": {"rms_db": -35.33, "peak_db": -2.7, "lufs": -31.0},
  "silences": [{"start": 0.0, "end": 0.5}],
  "peaks": {"rate": 2, "values": [0.0, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325,
                                   0.7325, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325, 0.7325,
                                   0.7325, 0.7325, 0.7325]}
}
```

`duration` always comes first; after it, only the features asked for, in this
order. `features=loudness,silence` answers `{"duration", "loudness",
"silences"}`. The feature is `silence`; its answer is `silences`.

| Key | What it is |
| --- | --- |
| `tempo` | librosa's tempo estimate in BPM, as `beat_track` makes it -- within about 1% for a steady tempo -- or `null` when the sound has no onsets at all |
| `beats` | The beat times librosa tracks, in seconds |
| `onsets` | The times notes, hits and syllables begin (librosa's onset detector), in seconds |
| `loudness.rms_db` | The RMS over every sample of every channel, in dBFS: a full-scale sine is -3.01 |
| `loudness.peak_db` | The largest sample, in dBFS |
| `loudness.lufs` | Integrated loudness (EBU R128 / ITU-R BS.1770) by ffmpeg's `ebur128`; `null` for silence, which the meter cannot integrate, or when ffmpeg cannot run |
| `silences` | Spans whose 10 ms RMS stays under `silence_db` for at least `silence_min` seconds, `{"start", "end"}` |
| `peaks` | `{"rate", "values"}`: window `i` covers `[i/rate, (i+1)/rate)` seconds, and its value is the largest absolute sample in it over all channels, as a fraction of full scale -- absolute, not scaled to the loudest window, so a quiet clip draws quiet. `ceil(duration * rate)` values |

Levels are floored at -120 dBFS, so digital silence reads `-120.0`, never
minus infinity. LUFS is gated, as BS.1770 says: a second of tone between two
of silence reads the tone's loudness, not a third of it.

Tempo, beats and onsets are read from the 22050 Hz mono copy with a 256-sample
hop; levels, silences and peaks from the sound at its own rate, so a peak is a
sample that was there. Nothing holds a whole signal in memory: an hour of 48
kHz stereo is read in blocks, and the results are librosa's own on the whole
signal (`Modules/Analysis.py`).

**Errors:** `404` for an id that is not here; `422` for an unknown feature
(`unknown feature 'pitch'; joe measures tempo, beats, onsets, loudness,
silence, peaks`) or a parameter out of bounds (`peaks_rate: Input should be
greater than or equal to 1`).

## `DELETE /api/media/{media_id}`

```bash
curl -X DELETE http://localhost:8010/api/media/6aceff6115ba4f4aa19d60b24f7c0a61
```

**`204 No Content`**, no body. `404` for an id that is not here -- never
uploaded, expired, or already deleted:

```json
{"detail": "no such media: it was never uploaded here, has expired, or was deleted"}
```

---

## Testing

`uv run pytest tests/` runs the media tests with the rest. They make their
media at test time -- click tracks, a tone between silences, a quiet room with
numpy; every container and codec with ffmpeg; nothing binary is committed --
and skip what needs ffmpeg when there is none (`JOE_FFMPEG`). Whisper is a
stand-in except in one test, marked `whisper_model`, which runs the real base
model from this machine's cache (it skips rather than download) on a sentence
said by the platform's own speech engine: Windows' SAPI voices, or espeak.
`-m "not whisper_model"` leaves it out.
