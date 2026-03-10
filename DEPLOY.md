`# Nano Bana Pro — Deployment Guide

## Architecture

```
Vercel (free)                         Render                        Ollama Cloud
┌─────────────────┐                  ┌──────────────────────────┐   ┌─────────────────┐
│  Next.js 15     │  HTTPS/JSON →    │  Web Service (Docker)    │──→│  Ollama Cloud   │
│  (frontend)     │  ← SSE stream    │  └── FastAPI backend     │   │  (hosted API)   │
│                 │                   │                          │   │  glm-4.7        │
│  Clerk Auth     │                   │  Managed PostgreSQL 16   │   │  GPU inference  │
│  (client-side)  │                   │  Managed Redis 7         │   └─────────────────┘
└─────────────────┘                  └──────────────────────────┘
         ↓                                      ↓
    Clerk Cloud                          Tavily (web search)
    (auth provider)
```

**No self-hosting needed.** Ollama Cloud provides an OpenAI-compatible API at `https://api.ollama.com/v1`. The backend calls it directly with your API key — no VPS, no relay, no local machine.

---

## Step 1: Backend — Deploy to Render

### 1a. One-click deploy with Blueprint

The repo includes `render.yaml` which defines all three services.

1. Go to [render.com/deploy](https://render.com/deploy)
2. Connect your Git repository
3. Render auto-detects `render.yaml` and provisions:
   - **nanobana-backend** — Docker web service
   - **nanobana-db** — Managed PostgreSQL 16
   - **nanobana-redis** — Managed Redis

### 1b. Set secret environment variables

In the Render dashboard, go to **nanobana-backend → Environment**:

```
OPENAI_API_KEY=your-ollama-cloud-api-key             # From Ollama Cloud dashboard
TAVILY_API_KEY=tvly-...                              # From tavily.com (optional)
CLERK_PUBLISHABLE_KEY=pk_live_...                    # From clerk.com dashboard
CLERK_SECRET_KEY=sk_live_...                         # From clerk.com dashboard
CLERK_JWT_ISSUER=https://...                         # From clerk.com → Sessions → JWT Issuer
CORS_ORIGINS=https://nanobana.vercel.app
```

`DATABASE_URL` and `REDIS_URL` are auto-injected by Render from the managed services.

### Ollama Cloud Setup

The backend calls Ollama Cloud's hosted API directly — no self-hosting, no VPS, no relay needed.

In the **Render dashboard → nanobana-backend → Environment**, set:
```
OPENAI_API_KEY=your-ollama-cloud-api-key
OPENAI_BASE_URL=https://api.ollama.com/v1
```

That's it. The backend uses the OpenAI-compatible endpoint with your API key.

### 1c. Database migration

Tables are created automatically on first startup — the backend runs `db/init.sql` (all `CREATE IF NOT EXISTS`) during container initialization. No manual migration needed.

### 1d. Verify

```bash
curl https://nanobana-backend.onrender.com/health
# → {"status":"ok","service":"nanobana-backend"}
```

### Render Pricing (Starter Pilot)

| Service | Plan | Cost |
|---------|------|------|
| Web Service (backend) | Starter | $7/mo |
| PostgreSQL | Starter (1GB) | $7/mo |
| Redis | Starter (25MB) | $0/mo (free) |
| **Render Total** | | **$14/mo** |

---

## Step 2: Frontend — Deploy to Vercel

### 2a. Connect repository

1. Go to [vercel.com/new](https://vercel.com/new)
2. Import your Git repository
3. Set **Root Directory** to `frontend`
4. Framework: **Next.js** (auto-detected)

### 2b. Set environment variables in Vercel dashboard

```
NEXT_PUBLIC_API_URL=https://nanobana-backend.onrender.com
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_SECRET_KEY=sk_live_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/
```

### 2c. Deploy

```bash
# Push to main — Vercel auto-deploys
git push origin main
```

Vercel gives you `https://nanobana.vercel.app` (or custom domain).

---

## Step 3: Clerk Setup

1. Create app at [clerk.com](https://clerk.com)
2. Get **Publishable Key** + **Secret Key** from the dashboard
3. Copy the **JWT Issuer URL** from Settings → Sessions
4. Configure **Allowed Redirect URLs**:
   - `https://nanobana.vercel.app/`
   - `http://localhost:3000/` (for local dev)
5. Set user roles via **Users → Select user → Public Metadata**:
   ```json
   { "role": "admin" }
   ```
   Default role (no metadata) = `analyst`

---

## Step 4: Verify End-to-End

```bash
# 1. Backend health
curl https://nanobana-backend.onrender.com/health

# 2. Frontend loads
open https://nanobana.vercel.app

# 3. Sign in via Clerk → run an analysis → verify SSE streaming works

# 4. Check backend logs in Render dashboard → Logs tab
```

---

## Cost Summary (Stakeholder Pilot, <10 users)

| Component | Service | Cost |
|-----------|---------|------|
| Frontend | Vercel (free tier) | $0 |
| Backend | Render Starter | $7/mo |
| PostgreSQL | Render Starter | $7/mo |
| Redis | Render Free | $0 |
| LLM | Ollama Cloud API (glm-4.7) | Pay-per-token |
| Auth | Clerk (free tier, 10K MAU) | $0 |
| Domain | Optional | $12/yr |
| **Total infra** | | **~$14/mo + LLM usage** |

*No VPS or self-hosting needed. Ollama Cloud is called directly via API key.*

---

## Render Gotchas

### SSE Streaming
Render supports long-running HTTP connections (SSE) on Starter+ plans. The default request timeout is 5 minutes. For long analyses, the pipeline's SSE events keep the connection alive (heartbeats).

### Cold Starts
Starter plan services spin down after 15 minutes of inactivity. First request takes ~30-60s to boot. Upgrade to **Standard ($25/mo)** for always-on.
- Workaround: set up a cron health check ping every 10 minutes (free via cron-job.org)

### ChromaDB Storage
ChromaDB data lives on the container's ephemeral filesystem. On Render, this resets on each deploy. Options:
- **Acceptable for pilot**: RAG collections rebuild on first use (SEC filings re-ingested)
- **For persistence**: Mount a Render Disk ($0.15/GB/mo) at `/app/chroma_data`

### Render Disk (optional, for ChromaDB persistence)
Add to `render.yaml` under the backend service:
```yaml
disk:
  name: chroma-data
  mountPath: /app/chroma_data
  sizeGB: 1
```

---

## Alternative: Self-Hosted Docker Compose

If you prefer a VPS over Render, the `docker-compose.yml` includes all services:

```bash
# On any VPS with Docker
git clone <repo> nanoai && cd nanoai
cp backend/.env.production backend/.env.production.local
# Edit .env.production.local with real keys
docker compose up -d --build
```

Add Caddy for HTTPS:
```
# /etc/caddy/Caddyfile
api.nanobana.com {
    reverse_proxy localhost:8000
}
```

---

## Local Development (unchanged)

```bash
# Terminal 1: databases
docker compose up postgres redis

# Terminal 2: backend
cd backend && uvicorn app.main:app --reload --port 8000

# Terminal 3: frontend
cd frontend && npm run dev
```

The `.env` file (local) still uses Ollama + dev-mode auth. No changes needed.

---

## Scaling Path

| Stage | Frontend | Backend | Database | Redis | LLM |
|-------|----------|---------|----------|-------|-----|
| **Pilot** (<10 users) | Vercel free | Render Starter $7 | Render Starter $7 | Render Free | Ollama Cloud API |
| **Growth** (100 users) | Vercel free | Render Standard $25 | Render Standard $20 | Render Pro $10 | Ollama Cloud API |
| **Scale** (1K+ users) | Vercel Pro $20 | Render Pro $85+ | RDS/Neon $65 | Upstash $25 | Ollama Cloud / self-hosted |
