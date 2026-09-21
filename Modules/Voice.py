"""Voice: speech analysis for a single audio source (transcription and mic capture).

Follows the same shape as Audio/Chroma/MIDI — a class wrapping one analysis
concern — so joe's speech-analysis path sits next to its music-analysis path
rather than beside it as a separate tool.
"""

import os
from datetime import datetime

import numpy as np
from scipy.io import wavfile


class Voice:
    """Speech-to-text and microphone capture, backed by whisper + sounddevice."""

    _model = None
    _model_size: str | None = None

    def __init__(self, model_size: str = "base", capture_dir: str | None = None):
        self.model_size = model_size
        self.capture_dir = capture_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "Voice"
        )

    @classmethod
    def _load_model(cls, model_size: str):
        """Load (and cache) the whisper model. Imported lazily — heavy and optional."""
        if cls._model is None or cls._model_size != model_size:
            import whisper

            cls._model = whisper.load_model(model_size)
            cls._model_size = model_size
        return cls._model

    def transcribe(self, file_path: str) -> dict:
        """Transcribe an existing audio file to text.

        Loads the audio with librosa (soundfile-backed) rather than handing
        whisper a path, so this does not depend on an `ffmpeg` binary being
        on PATH — whisper only shells out to ffmpeg when given a path.

        Returns: {"text": str, "segments": list, "language": str}
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        import librosa

        audio, _ = librosa.load(file_path, sr=16000, mono=True)
        model = self._load_model(self.model_size)
        result = model.transcribe(audio)
        return {
            "text": result.get("text", "").strip(),
            "segments": result.get("segments", []),
            "language": result.get("language"),
        }

    def record(self, duration: float = 5.0, sample_rate: int = 16000) -> str:
        """Record `duration` seconds from the default microphone to a WAV file.

        Returns the path written to.
        """
        import sounddevice as sd

        frames = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()

        os.makedirs(self.capture_dir, exist_ok=True)
        stamp = datetime.now().strftime("%m-%d-%y_%H-%M-%S")
        out_path = os.path.join(self.capture_dir, f"capture_{stamp}.wav")

        pcm16 = np.clip(frames[:, 0], -1.0, 1.0)
        pcm16 = (pcm16 * np.iinfo(np.int16).max).astype(np.int16)
        wavfile.write(out_path, sample_rate, pcm16)
        return out_path

    def listen(self, duration: float = 5.0, sample_rate: int = 16000) -> dict:
        """Record from the microphone and transcribe the result in one step."""
        wav_path = self.record(duration=duration, sample_rate=sample_rate)
        result = self.transcribe(wav_path)
        result["audio_path"] = wav_path
        return result
