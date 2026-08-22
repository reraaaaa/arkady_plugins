# Text Embedding Inference

Плагин-провайдер модели для собственного сервера [TEI](https://github.com/huggingface/text-embeddings-inference)
(Text Embeddings Inference) — предоставляет в Arkady типы моделей `rerank` и `text-embedding`.

## Наша конфигурация

Используется как реранкер для интеграции с CyberAI Vector
(см. плагин `cyberai-vector` в этой же директории): TEI запускает
`BAAI/bge-reranker-v2-m3` на сервере 180, а этот плагин предоставляет её
в Arkady как нативную Rerank-модель.

1. Запустить TEI на 180:
   ```bash
   docker run --gpus all -p 8080:80 -v tei_data:/data \
     ghcr.io/huggingface/text-embeddings-inference:latest \
     --model-id BAAI/bge-reranker-v2-m3
   ```
   Перед тем как полагаться на тег `latest` в проде, убедитесь, что образ
   реально собран под архитектуру GPU.
2. Установить этот плагин (Local Package).
3. Настройки → Провайдеры моделей → Text Embedding Inference → добавить учётные данные:
   - **Server url**: `http://10.198.96.180:8080`
   - **API Key**: оставить пустым, если TEI запущен без аутентификации
   - **Model Name**: `BAAI/bge-reranker-v2-m3` (только для отображения — TEI
     обслуживает одну модель на инстанс, значение просто должно совпадать
     с тем, что возвращает `/info`)
4. Сохранить — плагин сам вызовет `/info`, чтобы убедиться, что
   развёрнутая модель действительно реранкер, прежде чем принять учётные данные.

## Приватность

Плагин отправляет данные, необходимые для выбранной операции, только на
настроенный выше сервер TEI — больше никуда.
