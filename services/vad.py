"""Voice Activity Detection (VAD) utilities.

Silero VAD is primarily designed to run on the CLIENT (browser via ONNX/WASM
or mobile) to detect when the user is speaking vs silent. This reduces server
STT load by ~85% because only speech segments are sent to the server.

This module provides:
1. A server-side Silero VAD utility (optional, for processing uploaded chunks)
2. Client-side JavaScript snippet for browser VAD integration
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from silero_vad import load_silero_vad
    HAS_VAD = True
except ImportError:
    HAS_VAD = False
    logger.warning(
        "silero-vad not installed. Run: pip install silero-vad"
    )

import os
import numpy as np


class SileroVAD:
    """Server-side Silero VAD for voice activity detection.

    Uses the silero-vad Python package (PyTorch-based TorchScript model).
    Primarily, VAD should run on the client. This server-side class is useful
    for processing pre-recorded audio chunks or as a fallback.
    """

    def __init__(
        self,
        model_path: str | None = None,
        threshold: float = 0.5,
        sample_rate: int = 16000,
    ):
        if not HAS_VAD:
            raise RuntimeError(
                "silero-vad is required for Silero VAD. "
                "Run: pip install silero-vad"
            )

        self.model_path = model_path or os.getenv(
            "SILERO_VAD_MODEL", str(Path(__file__).parent.parent / "models" / "static" / "silero_vad.onnx")
        )
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.model = None
        self._load_model()

    def _load_model(self):
        try:
            self.model = load_silero_vad()
            logger.info("Silero VAD model loaded successfully")
        except Exception as exc:
            logger.exception("Failed to load Silero VAD model")
            self.model = None

    def is_speech(
        self,
        audio_samples: "np.ndarray",
        sample_rate: int | None = None,
    ) -> bool:
        """Detect if an audio chunk contains speech.

        Args:
            audio_samples: numpy array of float32 audio samples (normalized -1 to 1)
            sample_rate: sample rate of the audio (default: self.sample_rate)

        Returns:
            True if speech is detected, False otherwise.
        """
        if self.model is None:
            return True

        sr = sample_rate or self.sample_rate
        audio = np.asarray(audio_samples, dtype=np.float32).reshape(-1)

        try:
            from silero_vad import get_speech_timestamps
            timestamps = get_speech_timestamps(audio, self.model, sampling_rate=sr)
            return len(timestamps) > 0
        except Exception as exc:
            logger.exception("Silero VAD inference failed")
            return True

    def is_available(self) -> bool:
        return self.model is not None


# ---------------------------------------------------------------------------
# Client-side JavaScript for browser-based Silero VAD
# ---------------------------------------------------------------------------

CLIENT_VAD_JS = """
// Client-side Silero VAD — loads in browser via ONNX Runtime Web
// Only sends audio to server when speech is detected (reduces STT cost ~85%)

async function initClientVAD() {
    const ort = await import('https://cdn.jsdelivr.net/npm/onnxruntime-web/dist/ort.min.js');
    
    // Load Silero VAD model (host this on your server or use CDN)
    const modelUrl = '/models/static/silero_vad.onnx';
    const session = await ort.InferenceSession.create(modelUrl);
    
    return { session, ort };
}

async function isSpeechClient(audioBuffer, session, ort, sampleRate = 16000) {
    // Convert AudioBuffer to Float32Array
    const channelData = audioBuffer.getChannelData(0);
    const input = new ort.Tensor('float32', channelData, [1, channelData.length]);
    
    const feeds = {
        input: input,
        sr: new ort.Tensor('int64', BigInt64Array.from([sampleRate]), [1]),
    };
    
    const results = await session.run(feeds);
    const prob = results.output.data[0];
    
    return prob > 0.5; // threshold
}

// Usage pattern in your recorder:
// const vad = await initClientVAD();
// recorder.ondataavailable = async (e) => {
//   if (await isSpeechClient(e.data, vad.session, vad.ort)) {
//     speechBuffer.push(e.data);
//   } else if (speechBuffer.length > 0) {
//     await sendToServerSTT(speechBuffer);
//     speechBuffer = [];
//   }
// };
"""

# Make os available for the model path default
import os  # noqa: E402