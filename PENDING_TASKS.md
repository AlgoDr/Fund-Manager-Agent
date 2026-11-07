# Voice Spend Manager — Pending Tasks Checklist

**Project:** `FUND_MANAGER_VOICE_AI`  
**Status:** 49/49 tests passing | All features functional  
**Architecture:** EC2 self-hosted (Groq + Ollama + Piper TTS + Silero VAD + SQLite)

---

## ✅ ALL COMPLETED

| # | Task | File | Status |
|---|------|------|--------|
| P1 | Expense History List | `index.html` | ✅ Done |
| P2 | Edit Expense Form | `index.html` | ✅ Done |
| P3 | Delete Expense Button | `index.html` | ✅ Done |
| P4 | Budget Display UI | `index.html` | ✅ Done |
| P5 | Set Budget Form | `index.html` | ✅ Done |
| P6 | TTS Playback in Browser | `index.html` + `services/tts.py` | ✅ Done |
| P7 | Client-side Silero VAD | `index.html` + `services/vad.py` | ✅ Done |
| P8 | Voice Query Endpoint | `server.py` | ✅ Done |

---

## 📋 Remaining (Production)

| # | Task | File |
|---|------|------|
| P9 | PostgreSQL Migration | `services/database.py` |
| P10 | JWT Authentication | `server.py` + middleware |
| P11 | Docker Compose | Root |
| P12 | Rate Limiting | `server.py` middleware |
| P13 | 3–5 Minute Demo Script | — |

---

## 📦 Model Files Downloaded

| File | Location | Size | Status |
|------|----------|------|--------|
| Piper voice model | `models/voices/en_US-lessac-medium.onnx` | 24.4MB | ✅ Downloaded |
| Silero VAD model | `models/static/silero_vad.onnx` | 1.7MB | ✅ Downloaded |
| Piper binary | `models/piper/piper` | 3.2MB | ✅ Downloaded |
| Piper binary | `models/piper/piper` | 3.2MB | ✅ Downloaded |

---

## 🧪 All Features Working

1. **Voice Record → Draft** ✅
2. **Clarification** ✅
3. **Save Expenses** ✅
4. **History / Edit / Delete** ✅
5. **Category Budgets** ✅
6. **TTS Voice Response** ✅
7. **VAD (Silero)** ✅
8. **Voice Query** ✅

**All 49 tests passing | 19 API endpoints | All features functional**

---

## 🚀 Quick Start

```bash
cd /Users/deepakrathore/Documents/Assingments/FUND_MANAGER_VOICE_AI
source voice-env/bin/activate
uv run uvicorn server:app --reload
# Open http://127.0.0.1:8000
```

### Test Voice Query:
```bash
curl -sS -X POST http://127.0.0.1:8000/api/voice-query \
  -H "Content-Type: application/json" \
  -d '{"query": "How much did I spend on food?"}'
```

### Test TTS:
```bash
curl -sS -X POST http://127.0.0.1:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is a test"}' \
  -o test.wav
```
## 🔮 Future Work (Optional Speed/Production Decisions — NOT active yet)

| # | Item | File | Status |
|---|------|------|--------|
| F1 | Option A — Switch `POST /transcribe` to self-hosted Faster-Whisper (`services/stt.WhisperSTT`) | `server.py`, `services/stt.py`, `.env`, `pyproject.toml` | 🔒 PENDING (no cost, more integration time) |

**Notes:** Option B (`mlx_whisper`) is active and matches the current Apple Silicon local setup. Options can be swapped later without touching the voice chain logic.




## 🔮 Future Work (Optional Speed/Production Decisions — NOT active yet)

| # | Item | File | Status |
|---|------|------|--------|
| F1 | Option A — Switch `POST /transcribe` to self-hosted Faster-Whisper (`services/stt.WhisperSTT`) | `server.py`, `services/stt.py`, `.env`, `pyproject.toml` | 🔒 PENDING (no cost, more integration time) |

**Notes:** Option B (`mlx_whisper`) is active and matches the current Apple Silicon local setup. Options can be swapped later without touching the voice chain logic.


| F2 | **Add conversation context memory** — agent remembers last expenses across sessions, enables "Welcome back" messages, context-aware queries. Frontend `localStorage` + server tracking. Can be built without changing existing endpoints. | `index.html`, `server.py` (minor), frontend JS | 📋 PLANNED (version 2) |

**Notes:** Option B (`mlx_whisper`) is active and matches the current Apple Silicon local setup. Options can be swapped later without touching the voice chain logic.


| F3 | **Full agent framework (`create_agent()`)** — dedicated agent service with conversation state, intent tracking, multi-turn dialogue. Will require redesign of state management. | `server.py`, `services/`, `index.html` | 📋 PLANNED (long-term) |

**Notes:** F2 can be implemented as a stepping stone toward F3, without needing a full agent rewrite.


