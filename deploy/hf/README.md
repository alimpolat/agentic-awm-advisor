---
title: AWM AI Advisor Cockpit
emoji: 📊
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 8080
pinned: false
---

# AWM AI — Advisor Cockpit (POC)

Agentic advisor-flow demo over a fictitious Nordic UHNW family office. FastAPI + LlamaIndex
+ Vertex AI Gemini 2.5 (Pro/Flash) + embedded Qdrant hybrid retrieval, React + ECharts cockpit.

Requires Space secrets: `GCP_SA_KEY_B64` (base64 service-account key), `GCP_PROJECT_ID`, `INTEL_MODE`.
