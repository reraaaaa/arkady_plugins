# Text Embedding Inference

Model provider plugin for a self-hosted [TEI](https://github.com/huggingface/text-embeddings-inference)
(Text Embeddings Inference) server — provides `rerank` and `text-embedding`
model types in Arkady.

## Our setup

Used as the reranker for the CyberAI Vector integration
(see the `cyberai-vector` plugin in this same directory): TEI runs
`BAAI/bge-reranker-v2-m3` on server 180, this plugin exposes it as a native
Rerank model in Arkady.

1. Run TEI on 180:
   ```bash
   docker run --gpus all -p 8080:80 -v tei_data:/data \
     ghcr.io/huggingface/text-embeddings-inference:latest \
     --model-id BAAI/bge-reranker-v2-m3
   ```
   Verify the image tag is actually built for the GPU's architecture before
   relying on `latest` in production.
2. Install this plugin (Local Package).
3. Settings → Model Providers → Text Embedding Inference → add credentials:
   - **Server url**: `http://10.198.96.180:8080`
   - **API Key**: leave empty unless TEI was started with auth enabled
   - **Model Name**: `BAAI/bge-reranker-v2-m3` (label only — TEI serves one
     model per instance, this just needs to match what `/info` reports)
4. Save — the plugin calls `/info` itself to confirm the deployed model is a
   reranker before accepting the credentials.

## Privacy

This plugin sends the inputs required by the selected operation to the TEI
server configured above — no other upstream.
