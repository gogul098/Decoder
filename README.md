# Decoded

Live top-5 news in **Tech & AI, Indian Politics, World Politics, Terror & Security**. Each story is
decoded into the core idea, what changed, why, how, when, who it affects, the backstory built from
earlier news, and a readable narrative you can also **listen** to. The design is paper meets neo-brutalism:
thick ink outlines, hard shadows and a colour per story; cards are sheets with a folded corner that curls
when touched, and opening a story flips the page over to a colour-printed back before tossing it away.

```
 RSS (Google News) ──► ingester (cron in the workers, every 15 min)
                          │ writes today's top 5 to Redis + PUBLISH news:updates
                          ▼
                        Redis ◄──────────── queue + cache + shared model budgets
                          │ one subscription per API process
          ┌───────────────┼───────────────┐
        api #1          api #2          api #3     (behind nginx, least-busy routing)
          │  SSE  /api/stream             │  SSE  /api/decode/<id>/stream
          ▼                               ▼
     every open app: gets the top 5 instantly from Redis, then live pushes
     (phones never call RSS, and never talk to Redis directly)

 Open a story ─► queue ─► worker: earlier coverage ─► Groq (6 models, balanced) ─► Redis
                                   └─ PUBLISH decode:<id> progress: queued → finding → writing → ready
```

## Live news flow (SSE + Redis pub/sub)

- **Only the ingester touches RSS.** It runs inside the workers every `FEED_TTL_SECONDS`. A Redis lock
  makes sure only one worker ingests each category. It stores the ranked top 5 in Redis and publishes
  on `news:updates` only when the list changes.
- **The app opens one SSE stream at launch** (`/api/stream`). It immediately receives the current top 5
  for all four categories from Redis, then gets each new list the moment it's published. If you're
  looking at the list, a "New stories · show" pill appears instead of moving cards under your thumb.
- **Phones don't subscribe to Redis directly.** That would expose your database to the internet, and every
  phone would need its own Redis connection. Instead each API process keeps **one** Redis subscription
  and fans the messages out to all its connected phones. 10,000 open apps still means only a few Redis
  connections.
- **Decoding progress is live too** (`/api/decode/<id>/stream`). The app shows "Waiting for a free model →
  Read 6 earlier reports → Writing the story", then the result. Plain JSON endpoints remain as fallbacks.

## How it handles heavy traffic

- **Decode once, serve everyone.** When 1,000 people open the same story, only one Groq call happens
  (the job ID is the story ID). Everyone else gets the same live result. Results are cached for 24 h.
- **Queue + workers.** Requests never wait on Groq directly. To scale:
  `docker compose up -d --scale worker=6 --scale api=5`.
- **Multi-model balancer** (`backend/app/balancer.py`). Groq's limits are *per model*, so each model is its
  own lane with a requests-per-minute budget, counted atomically in Redis and shared by all workers.
  The best lane is picked by `weight × spare capacity × health ÷ in-flight`. On a 429 the lane cools down
  for Groq's `retry-after` and the job moves to the next model. Retired models are dropped automatically.
- **nginx** spreads traffic over the API replicas, keeps SSE streams unbuffered, and rate-limits abusive IPs.

Tested here with sample news and a stand-in LLM: 300 readers opening 20 stories at once over SSE →
exactly 20 model calls, all done in 1.2 s, spread over the 6 models by weight. An ingest published while
a phone was connected arrived on its stream immediately.

## 1. Run the backend (server)

Your laptop doesn't need to run this. Use any Linux server with Docker, for example an
Oracle Cloud *Always Free* VM, or a GitHub Codespace for quick testing.

```bash
git clone <your repo> && cd <repo>/backend
cp .env.example .env          # paste your Groq key(s) into GROQ_API_KEYS
docker compose up -d --build  # nginx on port 80
curl http://localhost/api/health
```

Check your real per-model limits at console.groq.com → Settings → Limits and adjust `GROQ_MODELS`
(`model:requests_per_minute:weight`). Put HTTPS in front (e.g. Cloudflare Tunnel or Caddy) if you
share the app.

## 2. Get the APK (no Android Studio needed)

1. Push this repo to GitHub.
2. Optional: Settings → Secrets and variables → Actions → **Variables** → `API_BASE` = your server address.
3. Actions tab → **Build APK** → Run workflow. In about 5 min the APK is under the run's artifacts and in
   the release named **latest**.
4. Install it on your phone (allow "install unknown apps"). If you skipped step 2, open ⚙ in the app and
   enter the server address.

## Local development

```bash
# backend, fully offline with sample data
cd backend && pip install -r requirements-dev.txt && pytest
redis-server &  NEWS_MOCK=1 LLM_MOCK=1 GROQ_API_KEYS=x arq app.worker.WorkerSettings &
NEWS_MOCK=1 LLM_MOCK=1 GROQ_API_KEYS=x uvicorn app.main:app --port 8000
# app
cd app && npm install && npm run dev      # then set the server to http://localhost:8000 in ⚙
```

## Settings (backend `.env`)

| Variable | Default | What it does |
|---|---|---|
| `GROQ_API_KEYS` | none | One or more keys, comma separated |
| `GROQ_MODELS` | 6 models | `model:rpm:weight` list, one lane per model per key |
| `NEWS_REGION` | `IN` | Google News edition |
| `FEED_TTL_SECONDS` | `900` | How often the ingester pulls RSS and publishes to Redis |
| `PREWARM` | `0` | `1` = decode every top story before anyone opens it (instant, but uses more Groq quota) |
| `WORKER_CONCURRENCY` | `8` | Jobs per worker process |
| `CLIENT_RPM` | `60` | Requests per minute allowed per phone/IP |

News comes from Google News RSS (headlines and short snippets only). The AI writes only from those
headlines, so the app shows every source and says when something is unclear.
