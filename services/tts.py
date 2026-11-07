"""Self-hosted TTS using Piper (runs on EC2 CPU, zero per-character API cost).

Piper is a lightweight, fast, local text-to-speech system.
- Model size: ~50-100MB per voice
- CPU-friendly, no GPU required
- Output: WAV audio that client plays back
- License: MIT

Voice models: https://huggingface.co/rhasspy/piper-voices
Recommended: en_US-lessac-medium (good quality, small)

To download a model:
    uv run python -m piper.download_voices en_US-lessac-medium --download-dir models/voices
"""
import logging
import os
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

PIPER_VOICES_DIR = Path(__file__).resolve().parent.parent / "models" / "voices"


class PiperTTS:
    """Self-hosted text-to-speech using Piper Python package."""

    def __init__(
        self,
        model_path: str | None = None,
    ):
        self.model_path = model_path or os.getenv(
            "PIPER_MODEL",
            str(PIPER_VOICES_DIR / "en_US-lessac-medium.onnx"),
        )
        self._voice = None
        self._load_model()

    def _load_model(self):
        """Load the Piper voice model."""
        if not Path(self.model_path).exists():
            logger.warning(
                "Piper TTS model not found at %s. "
                "Download with: uv run python -m piper.download_voices "
                "en_US-lessac-medium --download-dir models/voices",
                self.model_path,
            )
            return

        try:
            from piper import PiperVoice
            self._voice = PiperVoice.load(self.model_path)
            logger.info("Piper TTS model loaded: %s", self.model_path)
        except Exception as exc:
            logger.exception("Failed to load Piper TTS model: %s", exc)
            self._voice = None

    def is_available(self) -> bool:
        return self._voice is not None

    async def speak(
        self,
        text: str,
        output_path: str | None = None,
    ) -> str | None:
        """Generate a WAV file from text using Piper.

        Args:
            text: The text to synthesize.
            output_path: Path to save the WAV file. If None, a temp file is used.

        Returns:
            Path to the generated WAV file, or None if TTS is unavailable.
        """
        if not self._voice:
            logger.warning("Piper TTS model not loaded")
            return None

        if not text or not text.strip():
            return None

        if output_path is None:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            output_path = tmp.name
            tmp.close()

        try:
            # Run TTS in executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            output_path = await loop.run_in_executor(
                None, self._synthesize, text, output_path
            )
            return output_path
        except Exception as exc:
            logger.exception("Piper TTS error: %s", exc)
            return None

    def _synthesize(self, text: str, output_path: str) -> str:
        """Synchronous synthesis (runs in executor)."""
        import wave
        from piper import AudioChunk

        audio = bytearray()
        for chunk in self._voice.synthesize(text):
            if isinstance(chunk, AudioChunk):
                audio.extend(chunk.audio_int16_bytes)

        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(self._voice.config.sample_rate)
            wf.writeframes(bytes(audio))

        return output_path
