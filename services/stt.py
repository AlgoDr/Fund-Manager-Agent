"""Self-hosted STT using Faster-Whisper (runs on EC2, zero per-minute API cost).

This replaces MLX Whisper (macOS-only) and cloud Whisper APIs with a
Linux-compatible, self-hosted solution suitable for containerized EC2 deployment.

Model options (trade-off speed vs accuracy):
  - tiny:    ~1GB RAM, fastest, lowest accuracy
  - base:    ~1GB RAM, good balance
  - small:   ~2GB RAM, recommended for production starter
  - medium:  ~5GB RAM, better accuracy, more CPU
  - large-v3:~10GB RAM, best accuracy, needs GPU for low latency

Compute types:
  - int8:    CPU-efficient, slightly lower accuracy
  - float16: GPU-efficient, best accuracy on GPU
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False
    logger.warning(
        "faster-whisper not installed. "
        "Install with: pip install faster-whisper"
    )


class WhisperSTT:
    """Self-hosted speech-to-text using Faster-Whisper via CTranslate2."""

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        if not HAS_FASTER_WHISPER:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Run: pip install faster-whisper"
            )

        self.model_size = model_size or os.getenv("WHISPER_MODEL", "small")
        self.device = device or os.getenv("WHISPER_DEVICE", "cpu")
        self.compute_type = compute_type or os.getenv(
            "WHISPER_COMPUTE_TYPE", "int8"
        )

        self.model = None
        self._load_model()

    def _load_model(self):
        """Load the Whisper model into memory."""
        try:
            logger.info(
                "Loading Faster-Whisper model: size=%s device=%s compute=%s",
                self.model_size, self.device, self.compute_type,
            )
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info("Faster-Whisper model loaded successfully")
        except Exception as exc:
            logger.exception("Failed to load Faster-Whisper model")
            raise

    async def transcribe(self, audio_path: str, language: str = "en") -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path: Path to the audio file (wav, mp3, webm, etc.)
            language: Language code (e.g., "en", "hi")

        Returns:
            Transcribed text string.
        """
        if self.model is None:
            raise RuntimeError("Whisper model not loaded")

        try:
            segments, info = self.model.transcribe(
                audio_path,
                language=language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                beam_size=5,
            )

            text = " ".join(segment.text for segment in segments).strip()

            logger.info(
                "STT complete: lang=%s duration=%.2fs text=%s",
                info.language,
                info.duration,
                text[:100],
            )
            return text

        except Exception as exc:
            logger.exception("STT transcription failed")
            raise

    def is_available(self) -> bool:
        return self.model is not None