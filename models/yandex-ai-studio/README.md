## Overview

Плагин под **Yandex AI Studio** — текстовые (чат) модели. Тело запроса/ответа — стандартный OpenAI-совместимый `/chat/completions` (та же логика, что у generic `openai-api-compatible`), но два отличия, которые generic-плагин сам не умеет:

1. **Авторизация**: `Authorization: Api-Key <ключ>`, а не `Bearer <ключ>`.
2. **Адресация модели**: `gpt://<folder_id>/<model>`, а не голое имя — `folder_id` подставляется автоматически (`models/llm/llm.py`).

Только LLM (чат-модели). Embeddings/rerank/tts/speech2text и генерация изображений (`art://…`) — вне охвата этого плагина: в CyberAI Vector уже своя эмбеддинг-модель (BGE-M3, dense+sparse), а под остальное отдельного запроса не было.

## Источники

Официальная документация (`aistudio.yandex.ru`) на момент написания **блокирует ботов капчей** — ни `WebFetch`, ни прямой `curl` с браузерным `User-Agent` её не проходят. Технические детали (base URL, схема авторизации, формат model URI) взяты из исходников официального Python SDK: [`github.com/yandex-cloud/yandex-ai-studio-sdk`](https://github.com/yandex-cloud/yandex-ai-studio-sdk) (`_utils/http.py`, `_auth.py`, `_chat/base_function.py`).

Каталог моделей (`models/llm/*.yaml`) — из живой консоли Yandex AI Studio, сверен Алексеем вручную 2026-08-17. **Pricing не подтверждён** (заполнен нулями во всех yaml) — если нужен точный учёт стоимости, сверить с биллингом Yandex Cloud.

## Configure

Введи:
- **API Key** — статический API-ключ Yandex Cloud.
- **Folder ID** — идентификатор каталога Yandex Cloud (без него нельзя собрать `gpt://<folder_id>/<model>`).
- **API Base URL** — предзаполнен (`https://llm.api.cloud.yandex.net/v1`), менять не нужно, если не используется preprod-контур.

Для произвольной модели (`customizable-model`) в поле "Model Name" можно ввести либо короткое имя (`yandexgpt-5.1`), либо сразу готовый URI (`gpt://<folder_id>/yandexgpt-lite/latest@<суффикс>` — например, для дообученной модели).

## Известные ограничения / не проверено

- **Не тестировалось живым ключом** — у автора не было тестовых credentials Yandex Cloud на момент сборки плагина. Первый смоук-тест в UI Arkady обязателен перед использованием в проде.
- `top_p` / `frequency_penalty` / `presence_penalty` **намеренно не выставлены** в parameter_rules — официальный SDK (`ChatModelConfig`) не документирует их как поддерживаемые поля тела запроса; отправка неизвестных полей может дать `400` у строгих бэкендов.
- Поддержка `reasoning_content`/`<think>`-обёртки (как у generic `openai-api-compatible` для vLLM-моделей с thinking-mode) **не реализована** — если какая-то из моделей каталога начнёт возвращать reasoning-дельты в стриме, они уйдут как есть, без парсинга в отдельный блок.
- `user_identity_support` по умолчанию `no_support` (топ-уровневый параметр `user` не отправляется) — не подтверждено, принимает ли Yandex этот параметр.
