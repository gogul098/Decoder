# News Decoded

Live top-5 news in **Tech & AI, Indian Politics, World Politics, Terror & Security**, each story
decoded into: the core idea, what changed, why, how, when, who it affects, the backstory built from
earlier news, and a readable narrative you can also **listen** to. Synthwave-styled Android app.

```
 Android app ──► nginx (load balancer, least-busy + retry)
                   │
          ┌────────┼────────┐
        api #1   api #2   api #3        FastAPI: feeds, story status, per-IP limits
          └────────┼────────┘
                 Redis  ◄── queue + cache + shared model budgets
          ┌────────┼────────┐
       worker #1 worker #2 worker #3   arq: 8 jobs each, fetch previous news, call Groq
          └────────┼────────┘
        Groq: 6 models = 6 separate rate-limit lanes (more keys from other orgs = more lanes)
```

## How it handles heavy traffic

- **Decode once, serve everyone.** When 1,000 people open the same story, only one Groq call
  happens (the job ID is the story ID). Everyone else polls the cached result. Results are cached for 24 h.
- **Queue + workers.** Requests never wait on Groq directly. Jobs sit in Redis and any number of
  workers on any number of machines pull from it. To scale: `docker compose up -d --scale worker=6 --scale api=5`.
- **Multi-model balancer** (`backend/app/balancer.py`). Groq's limits are *per model*, so each model is its
  own lane with its own requests-per-minute budget, counted atomically in Redis and shared by all workers.
  The best lane is picked by `weight × spare capacity × health ÷ in-flight`. On a 429 the lane cools down
  for Groq's `retry-after` and the job moves to the next model instead of failing. Retired models are
  dropped automatically at startup.
- **nginx** spreads app traffic over the API replicas (least connections), retries a failed replica,
  and rate-limits abusive IPs.

Tested here with fake news + fake LLM: 200 simultaneous readers across 20 stories → exactly 20 model
calls, finished in 1.3 s, spread over all 6 models by weight, with two workers sharing the load.

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
| `FEED_TTL_SECONDS` | `900` | How often the top 5 refreshes |
| `PREWARM` | `0` | `1` = decode every top story before anyone opens it (instant, but uses more Groq quota) |
| `WORKER_CONCURRENCY` | `8` | Jobs per worker process |
| `CLIENT_RPM` | `60` | Requests per minute allowed per phone/IP |

News comes from Google News RSS (headlines and short snippets only). The AI writes only from those
headlines, so the app shows every source and says when something is unclear.
