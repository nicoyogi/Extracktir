# Deploying Extracktir

Extracktir is a small stateless FastAPI app shipped as a Docker image. It
listens on `$PORT` (default `8000`), exposes `/api/health` for probes, and
runs as a non-root user. It deploys cleanly to any platform that runs
containers.

Below are concrete recipes for the four most common targets.

---

## 1. Hugging Face Spaces (free, public)

Best for: a free public demo URL.

**One-time setup:**

1. Create a new Space at <https://huggingface.co/new-space>.
   - SDK: **Docker**
   - Hardware: CPU basic (free)
2. Push this repo to the Space. From a fresh clone:
   ```bash
   git remote add space https://huggingface.co/spaces/<user>/extracktir
   git push space main
   ```
3. Add a Spaces config block to the **top** of `README.md`:
   ```yaml
   ---
   title: Extracktir
   emoji: 📄
   colorFrom: green
   colorTo: blue
   sdk: docker
   app_port: 8000
   pinned: false
   ---
   ```
4. The Space will build the Dockerfile and serve the UI.

**Notes:**
- The free tier is **public** — anyone with the URL can upload PDFs.
  Use a private Space (paid) for confidential data.
- Build memory is generous (~16 GB) so OCR languages all fit.
- Spaces sleep after inactivity and wake on first request (~10–20 s).

---

## 2. Render (free, one-click GitHub deploy)

Best for: free hosting with auto-deploy from GitHub on push.

**Option A — one click:**

[Click here to deploy](https://render.com/deploy?repo=https://github.com/nicoyogi/Extracktir)

Render reads [`render.yaml`](./render.yaml) and provisions a Docker web
service with the right port, healthcheck, and env vars.

**Option B — dashboard:**

1. New → **Web Service** → connect your GitHub fork.
2. Runtime: **Docker**, plan: **Free** (or Starter for OCR).
3. Health check path: `/api/health`.

**Notes:**
- Free instances **sleep after 15 min** of inactivity (slow first request).
- Free RAM is **512 MB** — fine for digital PDFs, tight for multi-page OCR.
  Upgrade to Starter ($7/mo, 2 GB) if you'll OCR a lot.
- Upload limit is ~100 MB per request.

---

## 3. Fly.io (~$2–5/mo, global, fast)

Best for: low-latency global hosting, scale-to-zero between bursts.

```bash
fly launch --copy-config --no-deploy   # claims a unique app name
fly deploy
```

`fly.toml` is included. The default machine is shared-CPU / 512 MB and
stops when idle (`auto_stop_machines = "stop"`), so it costs ~$2–5/mo for
light use.

**Tuning:**
- For heavy OCR, bump `memory_mb = 1024` in `fly.toml`.
- For more languages, edit `Dockerfile` ARG: `TESSDATA_LANGS = "eng deu fra"`.

**Notes:**
- Fly's free tier is **no longer offered for new accounts** as of late
  2024. Expect a small monthly charge.
- Persistent volumes are not needed — the app is stateless.

---

## 4. Google Cloud Run (free tier, pay-per-request)

Best for: pay only for actual requests, scales to zero.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT
gcloud run deploy extracktir \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --port 8000
```

**Notes:**
- The default request size limit is **32 MB**. For larger PDFs add
  `--max-instances 5 --concurrency 4` and bump
  `--http2` + the request limit:
  ```bash
  gcloud run services update extracktir \
    --update-annotations=run.googleapis.com/request-size-limit=256Mi
  ```
- Free tier covers ~2M requests/month and 360 K vCPU-seconds.
- Cold starts: ~3–5 s for this image.

---

## 5. Any VPS / EC2 / Hetzner / DigitalOcean

If you have SSH access to a Linux box with Docker:

```bash
git clone https://github.com/nicoyogi/Extracktir
cd Extracktir
docker compose up -d --build
```

Then put nginx or Caddy in front for TLS:

```nginx
server {
  server_name extracktir.example.com;
  location / { proxy_pass http://127.0.0.1:8000; client_max_body_size 100M; }
  listen 443 ssl;
  # ... letsencrypt cert paths ...
}
```

---

## Things to know before exposing it publicly

The current build is intentionally minimal. If you put it on the public
internet, consider adding:

- **Auth.** There's no login. Anyone who finds the URL can upload PDFs.
  Easy options: stick it behind Cloudflare Access, an nginx basic-auth
  block, or add a FastAPI dependency that checks an `X-Api-Key` header.
- **Upload limits.** PDFs and OCR are CPU/RAM heavy. Reverse proxies
  default to small body limits — bump them, but also cap concurrency.
- **Storage.** The app keeps nothing on disk by default. Uploaded PDFs
  live in memory for the request and are then garbage-collected.
- **Rate limiting.** Add `slowapi` or your reverse proxy's rate limiter
  if the URL is public.
- **CORS.** Currently same-origin only (the UI is served from `/`). If
  you want to call the API from a different domain, add
  `from fastapi.middleware.cors import CORSMiddleware` to `extracktir/web.py`.

If any of these would help, ask and I'll wire it in.
