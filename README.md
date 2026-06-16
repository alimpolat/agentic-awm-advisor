# Agentic Investment-Advisor RAG — a working reference build

**A multi-agent system that reads a private-wealth client's situation, gathers live market intelligence, and writes a grounded, fully-cited investment briefing — then answers follow-up questions from the same evidence.** Built solo, deployed, and runnable in your browser.

Every recommendation is cited to a source document and chunk; when the evidence isn't there, the system says **"I don't know"** rather than inventing an answer.

**▶ Live demo:** available on request

> Originally built as a private-banking advisor demonstrator (a Nordic UHNW persona). The **engine underneath is domain-agnostic** and maps directly onto institutional investment workflows — due-diligence prep, portfolio & risk monitoring, market-intelligence briefs, and IC-memo drafting. This README is written so an engineer can navigate the design and find the code for each capability quickly.

---

## What it does, in one minute

An advisor opens the cockpit and a **Monday brief is already written**: what changed over the weekend that touches this client's portfolio, the macro picture, relevant news, a risk panel, and three **next-best-actions — each cited to a source**. Below the brief, an **advisor chat** answers questions about the portfolio/policy from the same grounded corpus.

The brief is **pre-generated and served from cache** (not on the request path), so the page is instant; the chat runs the live retrieval pipeline per question.

---

## Architecture at a glance — a 5-stage agentic pipeline

```
Stage 1 ─ Opportunity-Scout ─┐
                             ├─▶ Stage 3a ─ Planner ─▶ ┌─ 3b Intel-Gathering ─┐
Stage 2 ─ Client-Insights  ─┘   (decomposes the          ├─ 3c Macro          │
   (run in parallel)             brief into              ├─ 3d Portfolio      ├─▶ Stage 4 ─ Synthesizer
                                 sub-questions)          └─ 3e News           │     (assembles + grounds
                                                          (run in parallel)   ┘      every claim → cited brief)
```

Work is split across **eight specialist agents** coordinated by a planner — each has one job, so the system is debuggable and **each stage is independently measurable and testable**. Stages 1+2 and 3b–e run **concurrently** (`asyncio.gather`), so the brief is assembled from focused, separately-checkable passes rather than one giant prompt.

- **Orchestration** is hand-built async Python (`app/orchestrator.py`) for full control and parallelism — no heavyweight workflow framework on the hot path. (For a production, audit-critical platform the natural step up is a graph orchestrator — LangGraph / Microsoft Agent Framework — for checkpointing and human-in-the-loop gates.)
- **Typed contracts everywhere:** every agent returns a validated **Pydantic** model (`app/schemas.py` — `BriefSchema`, `NBA` with `evidence_refs`, `RiskFlag`, `ClientSnapshot`), so downstream stages consume structured data, not prose.

| Stage | Agent | Job |
|---|---|---|
| 1 | Opportunity-Scout | What's relevant to this client right now? |
| 2 | Client-Insights | Build the client picture (portfolio, IPS, meeting history) |
| 3a | Planner | Decompose the brief into per-specialist sub-questions |
| 3b | Intel-Gathering | Retrieve over the client corpus (the RAG core) |
| 3c | Macro | Rates / FX / regime read |
| 3d | Portfolio | Holdings exposure vs the investment policy statement |
| 3e | News | Live + snapshot market news |
| 4 | Synthesizer | Assemble the brief and **ground every claim to a source** |
| — | Chat | Follow-up Q&A over the same grounded corpus |

---

## The retrieval & grounding stack

Production-grade RAG is *recall wide → sharpen for precision → ground every claim → measure.* The retriever (`app/retrieval/`) is built explicitly, stage by stage:

| Stage | What it does | File |
|---|---|---|
| **Chunking** | Structure-aware chunking of the source corpus | `retrieval/chunker.py` |
| **Contextual retrieval** | For each chunk, Gemini 2.5 Flash writes a 1–3 sentence context that locates it in its parent doc; prepended **before embedding** to fix out-of-context fragments (Anthropic's technique). Generated contexts are **cached to disk** so re-indexes are free after the first pass. | `retrieval/contextual.py` |
| **Embeddings** | `gemini-embedding-001`, **task-typed** (`RETRIEVAL_QUERY` vs `RETRIEVAL_DOCUMENT`), 768-d — task-typed embeddings beat generic vectors on relevance | `retrieval/embedder.py` |
| **Dense search** | Qdrant cosine ANN, top-30 | `retrieval/qdrant_store.py` |
| **Sparse search** | BM25 (rank_bm25), top-30 — catches exact tickers/terms dense misses | `retrieval/bm25.py` |
| **Fusion** | Reciprocal Rank Fusion (**RRF, k=60**), keep top-20 | `retrieval/hybrid.py` |
| **Rerank** | Gemini 2.5 Flash **listwise reranker** → final **top-5** | `retrieval/reranker.py` |
| **Grounded generation** | Synthesizer writes each claim with `evidence_refs` (doc_id + chunk); UI shows click-through provenance; **refuses** ("I don't know") when unsupported | `app/agents/synthesizer.py` |

**The honest design note:** hybrid (dense + sparse) gives recall from both semantic *and* keyword signals; the listwise reranker gives precision so the model sees five highly-relevant passages, not thirty near-misses. Parameters (`dense=30, bm25=30, RRF k=60, keep 20, top_k=5`) are documented in `hybrid.py` and came from a written SOTA-RAG review (`docs/research/`).

---

## Evaluation & observability

The build isn't "trust me, it's grounded" — retrieval and faithfulness are **measured** and every run is **traced**.

| Metric (Ragas, on the synthetic eval set) | Value |
|---|---|
| Context recall @5 | **≈ 0.909** |
| Faithfulness | **≈ 0.963** |
| Answer relevancy | **≈ 1.000** |

- **Ragas** harness (`eval/run_ragas.py`, `eval/generate_questions.py`) with a **per-intent breakdown** (`eval/results/ragas_per_intent.csv`) — the LLM-judge runs on Gemini Flash (no extra API keys).
- **Phoenix (Arize, OSS)** tracing via `openinference-instrumentation-llama-index` (`app/observability.py`) — every retrieval + generation span is inspectable (`eval/results/phoenix_trace_brief.png`).
- **Hand review** of outputs (`eval/results/hand_review.html`) alongside the automated scores.
- *Honest scope:* the numbers are on a **small synthetic question set** for a single persona — they demonstrate the eval discipline (measured, per-intent, traced, regressible), not a production benchmark.

---

## Live intelligence — current yet reproducible

The News/Intel layer pulls from a live market-signal feed (`app/intel/world_monitor_client.py`) with a **deterministic snapshot fallback** (`app/intel/snapshot_loader.py`): live where reachable, a frozen snapshot otherwise — so demos and evals are **stable and reproducible** rather than flaky.

---

## Frontend

`frontend/` — **React 19 + Vite + Tailwind + Apache ECharts** (`echarts-for-react`). A single-page advisor cockpit: the brief, an allocation **donut**, opportunity flags, a risk panel, **next-best-action cards with citation chips**, and the advisor chat. Charts are animated and themed to one palette.

---

## Deployment

- **Containerised** (`Dockerfile`) → **Cloud Run** `europe-west1` via `cloudbuild.yaml`; models on **Vertex AI** `us-central1`. Live demo mirrored on **Hugging Face Spaces**.
- **Azure production target** (for an enterprise / sovereign-fund context): the architecture ports cleanly — **Azure OpenAI / Foundry** models (Provisioned PTU for data residency), **Azure AI Search** (hybrid + semantic ranker + agentic retrieval) in place of Qdrant+BM25, **Document Intelligence** for filings/forms, **AKS** for serving, behind **private endpoints + customer-managed keys + a no-training posture**.

---

## Where to look — engineering topics → code

| Topic | In this repo |
|---|---|
| Production RAG | `app/retrieval/hybrid.py` (the full pipeline) |
| Chunking strategy | `retrieval/chunker.py` + `retrieval/contextual.py` |
| Embedding selection / task-typed | `retrieval/embedder.py` |
| Hybrid + RRF + reranking | `retrieval/{bm25,hybrid,reranker}.py` |
| Agentic orchestration / multi-agent | `app/orchestrator.py` + `app/agents/*` |
| Typed agent I/O (structured outputs) | `app/schemas.py` |
| Grounding / cited generation / refusal | `app/agents/synthesizer.py` |
| Eval (Ragas) + tracing (Phoenix) | `eval/*` + `app/observability.py` |
| Live-or-deterministic data | `app/intel/*` |
| API surface | `app/main.py` |
| Frontend | `frontend/src/*` |
| Full design write-ups | [`ARCHITECTURE.html`](ARCHITECTURE.html) · [`EVAL.html`](EVAL.html) |

---

## How this maps to an investment-management platform

| Build component | Investment use case |
|---|---|
| Opportunity-Scout | Deal/opportunity surfacing · due-diligence prep |
| Client-Insights | Portfolio / mandate context |
| Macro · Portfolio · Intel · News specialists | Macro-risk read · exposure analysis · market intelligence |
| Synthesizer + grounding | Board-ready, cited investment briefs / IC memos |
| Cited evidence + "I don't know" refusal | No-fabrication discipline — essential where a wrong figure moves money |

The same pattern serves portfolio optimisation, risk monitoring, and IC-memo drafting: a generation core wrapped in a grounding layer and an eval harness, deployed so nothing reaches the user until it's measured.

---

## Run locally

**Prerequisites:** Python 3.12 + [uv](https://docs.astral.sh/uv/) + a GCP service-account JSON with Vertex AI permissions.

```bash
git clone https://github.com/alimpolat/agentic-awm-advisor
cd agentic-awm-advisor
uv sync --extra dev
cp .env.example .env                                  # fill in your own values
uv run --no-sync python scripts/smoke_vertex.py       # verify Vertex auth
uv run --no-sync uvicorn app.main:app --port 8001 --reload
# frontend (separate terminal):  cd frontend && npm install && npm run dev
```

**Rebuild the brief + index, run the suite:**

```bash
uv run --no-sync python -m app.orchestrator           # regenerate the 5-stage brief
uv run --no-sync python scripts/build_index.py        # build Qdrant + BM25 index
uv run --no-sync pytest -m "not live" -q              # offline test suite (only 3 tests hit live Vertex)
```

The pytest suite covers every agent (`tests/test_agents/*`), the retrieval stack (`test_chunker`, `test_contextual`, `test_embedder`, `test_reranker`, `test_retrieval`), schemas, the API, and an end-to-end smoke test.

---

## Honest scope

This is a **proof-of-concept**. The Bergström family office and all associated data are **fictitious**; the system is not connected to any live financial data or production systems. It exists to demonstrate, end to end, how I build **grounded, evaluated, agentic LLM systems** for high-stakes domains — and it's genuinely deployed and runnable, not slideware.

---

## Repository layout

<details>
<summary>Click to expand</summary>

```
agentic-awm-advisor/
├── app/
│   ├── main.py               # FastAPI app, /api routes
│   ├── orchestrator.py       # 5-stage async pipeline (asyncio.gather)
│   ├── schemas.py            # Pydantic contracts (BriefSchema, NBA, RiskFlag, …)
│   ├── agents/               # one module per stage-agent (8 + chat)
│   ├── retrieval/            # chunker · contextual · embedder · bm25 · hybrid · reranker · qdrant_store
│   ├── intel/                # World_Monitor client + deterministic snapshot fallback
│   ├── llm/                  # Vertex AI client + prompt loader
│   └── observability.py      # Phoenix tracing
├── frontend/                 # React 19 + Vite + Tailwind + ECharts
├── eval/                     # Ragas harness + results (per-intent CSV, Phoenix trace, hand review)
├── data/                     # corpus, fixtures, cached brief/snapshot
├── scripts/                  # build_index · fetch_corpus · smoke_vertex · probes
├── tests/                    # per-agent + retrieval + schema + e2e tests
├── Dockerfile · cloudbuild.yaml      # Cloud Run deploy
├── ARCHITECTURE.html · EVAL.html     # full styled design + eval write-ups
└── pyproject.toml
```
</details>

---

*Built solo as a reference for how I design grounded, evaluated, agentic LLM systems for high-stakes domains. — Alim Polat*
