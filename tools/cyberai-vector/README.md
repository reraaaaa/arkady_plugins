## cyberai-vector

**Author:** cyberai-vector
**Version:** 0.0.5
**Type:** tool

### Description

Search and RAG answers over Russian federal information-security regulations
(НПА РФ) and an information-security best-practices library, backed by the
CyberAI Vector service (`Arkady_Cyber/src/cyberai_vector/api.py`) — hybrid
Qdrant search (BGE-M3 dense+sparse) with a cross-encoder reranker.

### Setup

1. Run the CyberAI Vector service (`api.py`) somewhere reachable from this
   Arkady instance — locally: `.venv/bin/uvicorn cyberai_vector.api:app
   --host 0.0.0.0 --port 8001`.
2. In this plugin's provider settings, fill in:
   - **Base URL** — where `api.py` is reachable. From Arkady running in
     Docker on the same machine as `api.py`: `http://host.docker.internal:8001`.
     On the production server layout: `http://10.198.96.180:8001`.

### Usage

Two tools, add them to an Agent-mode app:

- **search_npa** — raw search over Russian federal IB regulations. Returns
  matched fragments with full metadata (citation, obligation, legal rank,
  status, domains).
- **search_bestpractices** — same, over the IB best-practices library
  (ISO/IEC 27002 etc.) — not Russian law, a supplementary reference.

Both are raw retrieval tools meant to be called repeatedly by the agent's own
reasoning loop (multiple targeted queries, cross-checking gaps) rather than
a single one-shot call — that's the agent's job, not this plugin's.
