# Voice Spend Manager — Deployment Plan (EC2 Self-Hosted)

## Overview
- **Target:** 10,000 users
- **Host:** EC2 (single instance to start, horizontal scale later)
- **Economy:** Zero per-API fees — only EC2 infrastructure cost
- **Containerization:** Docker Compose ready
- **Architecture:** Fully self-hosted STT + LLM + TTS + VAD + DB

---

## Architecture Decisions (FIXED)

| Layer | Selection | Reasoning |
|-------|-----------|-----------|
| **STT** | Faster-Whisper (self-hosted) | Runs on EC2 CPU/GPU, MIT license, no per-minute cost |
| **LLM** | Ollama (self-hosted Llama-3.1-8B) | Runs on EC2, no per-token cost, already integrated |
| **TTS** | Piper TTS (self-hosted) | ~50MB, CPU-friendly, zero latency, no per-char cost |
| **VAD** | Silero VAD (client-side ONNX) | Reduces server STT load by ~85%, runs in browser |
| **DB** | PostgreSQL | SQLite cannot handle 10K concurrent writers |
| **Cache** | Redis | Rate limiting, idempotency keys, session cache |
| **Auth** | JWT-based | Replace `user_id="local-user"` placeholder |

---

## Why NOT SQLite for 10K Users

SQLite is a single-file database with **writer locks**. Even with WAL mode:
- Concurrent `INSERT`/`UPDATE` operations will get `database is locked` errors
- No connection pooling beyond one writer
- No row-level locking
- Not suitable for 10K concurrent users

**PostgreSQL is required for production.** Migration path documented below.

---

## EC2 Instance Recommendations

| Tier | Instance | vCPU | RAM | Monthly Cost | Users |
|------|----------|------|-----|--------------|-------|
| Starter | t3.medium | 2 | 4 GB | ~$35 | 1K–2K |
| Scaled | t3.xlarge | 4 | 16 GB | ~$145 | 5K–8K |
| High | g4dn.xlarge (GPU) | 4 | 16 GB + GPU | ~$280 | 10K+ |

**Start with t3.xlarge.** Add GPU instance if STT/LLM latency becomes a bottleneck.

---

## Installation Steps

### 1. Provision EC2
```bash
# Launch Ubuntu 22.04 LTS on EC2
# Security Group: open 80 (HTTP), 443 (HTTPS), 8000 (API), 22 (SSH)
# Attach EBS volume: 100 GB gp3
```

### 2. Install Docker & Docker Compose
```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose nginx
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker
```

### 3. Clone Project & Configure
```bash
git clone <your-repo>
cd FUND_MANAGER_VOICE_AI

# Create .env (NEVER commit this)
cat > .env << 'ENV'
GROQ_API_KEY=your_groq_key          # Keep as fallback only
OLLAMA_MODEL=gemma2:2b              # Self-hosted primary
OLLAMA_BASE_URL=http://ollama:11434
DB_HOST=postgres
DB_PORT=5432
DB_NAME=voice_spend
DB_USER=voice_app
DB_PASS=change_this_production_password
REDIS_HOST=redis
REDIS_PORT=6379
JWT_SECRET=change_this_to_random_string
ENV

chmod 600 .env
```

### 4. Download Piper TTS Voice Models
```bash
mkdir -p voices
# Download a lightweight English voice
curl -L -o voices/en_US-lessac-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -L -o voices/en_US-lessac-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

### 5. Download Silero VAD Model (Client-side)
The VAD model is loaded in the browser via ONNX Runtime Web. No server download needed — it's bundled with the frontend.

### 6. Docker Compose
Create `docker-compose.yml` (see below).

### 7. Deploy
```bash
docker-compose up -d
docker-compose logs -f
```

---

## Docker Compose (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx:/etc/nginx/conf.d
      - ./certbot/conf:/etc/letsencrypt
    depends_on:
      - app
    restart: unless-stopped

  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=voice_spend
      - DB_USER=voice_app
      - DB_PASS=${DB_PASS}
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - JWT_SECRET=${JWT_SECRET}
    depends_on:
      - ollama
      - postgres
      - redis
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: voice_spend
      POSTGRES_USER: voice_app
      POSTGRES_PASSWORD: ${DB_PASS}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped

volumes:
  ollama_data:
  postgres_data:
```

---

## Dockerfile (Multi-stage, Container-ready)

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# System dependencies for Faster-Whisper + Piper
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv pip install --system -r pyproject.toml

# Additional production deps
RUN pip install faster-whisper asyncpg redis python-multipart

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Start command
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Migration Path: SQLite → PostgreSQL

### Phase 1: Keep SQLite for local development (current)
- `services/database.py` uses SQLite
- Fine for demo and testing

### Phase 2: Add PostgreSQL support (before production)
```python
# services/database.py — dual mode
import os
import sqlite3
import asyncpg

USE_POSTGRES = os.getenv("USE_POSTGRES", "false").lower() == "true"

if USE_POSTGRES:
    _pool = None
    async def get_pool():
        global _pool
        if _pool is None:
            _pool = await asyncpg.create_pool(...)
        return _pool
else:
    def get_connection():
        # Existing SQLite code
        ...
```

### Phase 3: Full PostgreSQL in production
- Set `USE_POSTGRES=true` in `.env`
- Run schema migration
- Update all endpoints to use asyncpg

---

## Rate Limiting (Per-User RPM)

```python
# Middleware using Redis
def check_rate_limit(user_id: str, limit: int = 30, window: int = 60):
    key = f"rate_limit:{user_id}"
    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, window)
    if current > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
```

---

## Monitoring & Health Checks

```python
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "stt": "faster-whisper",
        "llm": "ollama",
        "tts": "piper",
        "db": "postgresql",
        "redis": "connected"
    }
```

---

## Estimated Monthly Cost (EC2 only)

| Component | Cost |
|-----------|------|
| t3.xlarge EC2 | ~$145/month |
| EBS 100 GB | ~$10/month |
| Data transfer | ~$10/month |
| **Total** | **~$165/month** |

**vs. Multiple Cloud APIs:** $300–$2,000+/month for STT + LLM + TTS at 10K users.

---

## Next Steps (Priority Order)

1. ✅ Architecture diagram — saved to `architecture_diagram.txt`
2. ✅ Deployment plan — this file
3. **Next:** Create `services/stt.py` (Faster-Whisper)
4. **Next:** Create `services/tts.py` (Piper)
5. **Next:** Create `services/vad.py` (Silero client-side JS)
6. **Next:** Update `server.py` to use self-hosted services
7. **Next:** Migrate `services/database.py` to PostgreSQL
8. **Next:** Add JWT auth middleware
9. **Next:** Create `docker-compose.yml` and `Dockerfile`
10. **Next:** Frontend updates for voice response playback

