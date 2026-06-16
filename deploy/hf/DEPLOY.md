# HF Spaces Deployment Runbook

## Prerequisites
- Hugging Face account with a write token (Settings > Access Tokens).
- An empty Docker Space created at https://huggingface.co/new-space
  (SDK = Docker, visibility = Public or Private).
- Git LFS installed locally (`git lfs install`).

## Files required in the Space repo (root)
The Space repo IS this project repo — push it directly. The multi-stage Dockerfile
builds the React frontend inside the image, so no pre-built assets are needed.

Required paths (relative to repo root):
  Dockerfile
  pyproject.toml
  uv.lock
  app/                         (Python source + schemas + agents etc.)
  frontend/                    (React source, minus node_modules/ and dist/)
  data/                        (JSON caches + corpus/*.html — PDFs excluded by .dockerignore)
  qdrant_data/                 (embedded Qdrant collection, ~1.5 MB — no LFS needed)
  bm25.json                    (~232 KB — no LFS needed)
  README.md                    (copy from deploy/hf/README.md to the Space root)

HF LFS threshold is 10 MB. All data files in this repo are well below that threshold,
so LFS is not required. If you add larger files in the future (>10 MB), run:
  git lfs track "path/to/largefile"
  git add .gitattributes

## Step-by-step

### 1. Clone the Space repo
  git clone https://huggingface.co/spaces/<user>/<space> hf-space
  cd hf-space

### 2. Sync project files into the Space repo
Copy the following from this project into the Space repo root:
  Dockerfile
  pyproject.toml
  uv.lock
  app/
  frontend/
  data/                        (omit data/corpus/*.pdf and data/contextual_cache/)
  qdrant_data/
  bm25.json
  .dockerignore

Copy deploy/hf/README.md to the Space repo root as README.md.
  cp <project>/deploy/hf/README.md README.md

Do NOT copy: .git, .venv, docs/, scripts/, tests/, lore/, html-output/,
  gg-gcpsbprojs-*.json, .env, any *.pdf files, data/contextual_cache/.

### 3. Set Space secrets (before or after push — build will retry on first run with secrets)
In the Space Settings > Variables and secrets UI, add:

  GCP_SA_KEY_B64   = <base64-encoded service-account key, single line>
  GCP_PROJECT_ID   = gg-gcpsbprojs-004
  INTEL_MODE       = auto

To generate GCP_SA_KEY_B64 on Linux/macOS:
  base64 -w0 gg-gcpsbprojs-004-*.json

On Windows (PowerShell):
  [Convert]::ToBase64String([IO.File]::ReadAllBytes("gg-gcpsbprojs-004-*.json"))

NEVER commit the key file to the repo.

### 4. Push to HF Spaces
  git add .
  git commit -m "deploy: AWM AI Advisor Cockpit"
  git push

HF will start a Docker build automatically. Build takes approximately 5-8 minutes
(npm ci + vite build in stage 1, uv sync in stage 2).

### 5. Verify
Once the build completes, the Space URL is:
  https://<user>-<space>.hf.space

Smoke checks:
  GET  https://<user>-<space>.hf.space/healthz          -> {"ok": true}
  GET  https://<user>-<space>.hf.space/                 -> HTML with id="root"
  GET  https://<user>-<space>.hf.space/api/brief/bergstrom  -> JSON brief (cached)
  POST https://<user>-<space>.hf.space/api/chat
       {"client_id":"bergstrom","question":"What is the Gulf real estate exposure?"}
       -> JSON with live Vertex AI answer

### 6. Monitor build logs
  In the Space UI: "Factory restarting" -> "Building" -> "Running"
  Or via CLI: huggingface-hub>=0.24 supports `huggingface-cli` with log streaming.

## Troubleshooting
- If build fails with "npm ERR! code ERESOLVE": The lockfile may be stale.
  Rebuild locally: cd frontend && npm install --legacy-peer-deps && cd ..
  Commit the updated package-lock.json and push again.
- If container starts but Vertex calls fail: Check that GCP_SA_KEY_B64 is set as a
  Space secret (not a variable — secrets are hidden from build logs). Verify the
  key has the Vertex AI User IAM role on the GCP project.
- If the Space shows "Port 8080 not open": The app may have crashed. Check the
  Space logs for Python tracebacks.
