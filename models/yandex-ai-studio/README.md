## Overview

Плагин под **Yandex AI Studio** — текстовые (чат) модели. Тело запроса/ответа — стандартный OpenAI-совместимый `/chat/completions` (та же логика, что у generic `openai-api-compatible`), но два отличия, которые generic-плагин сам не умеет:

1. **Авторизация**: `Authorization: Api-Key <ключ>`, а не `Bearer <ключ>`.
2. **Адресация модели**: `gpt://<folder_id>/<model>`, а не голое имя — `folder_id` подставляется автоматически (`models/llm/llm.py`).

Только LLM (чат-модели). Embeddings/rerank/tts/speech2text и генерация изображений (`art://…`) — вне охвата этого плагина: в CyberAI Vector уже своя эмбеддинг-модель (BGE-M3, dense+sparse), а под остальное отдельного запроса не было.

**Почему именно OpenAI-совместимый эндпоинт, а не «родной» gRPC/REST Foundation Models API Yandex** — у Yandex Cloud два параллельных API-поверхности с разной полнотой фич (см. `github.com/yandex-cloud/cloudapi`, `yandex/cloud/ai/foundation_models/v1/text_generation/text_generation_service.proto`): в специализированном API поле `tools` в `CompletionRequest` присутствует в схеме, но explicitly помечено как **`unsupported, ignored`** — tool-calling там не поддерживается вообще. OpenAI-совместимый `/v1/chat/completions`, которым пользуется этот плагин, tool-calling поддерживает и был проверен живым ключом (см. ниже) — это не совпадение, а причина выбора именно этого эндпоинта.

## Источники

Официальная документация (`aistudio.yandex.ru`) на момент написания **блокирует ботов капчей** — ни `WebFetch`, ни прямой `curl` с браузерным `User-Agent` её не проходят. Технические детали (base URL, схема авторизации, формат model URI) взяты из исходников официального Python SDK: [`github.com/yandex-cloud/yandex-ai-studio-sdk`](https://github.com/yandex-cloud/yandex-ai-studio-sdk) (`_utils/http.py`, `_auth.py`, `_chat/base_function.py`).

Каталог моделей (`models/llm/*.yaml`) — из живой консоли Yandex AI Studio, сверен Алексеем вручную 2026-08-17. **Pricing не подтверждён** (заполнен нулями во всех yaml) — если нужен точный учёт стоимости, сверить с биллингом Yandex Cloud.

## Configure

Введи:
- **API Key** — статический API-ключ Yandex Cloud.
- **Folder ID** — идентификатор каталога Yandex Cloud (без него нельзя собрать `gpt://<folder_id>/<model>`).
- **API Base URL** — предзаполнен (`https://llm.api.cloud.yandex.net/v1`), менять не нужно, если не используется preprod-контур.

Для произвольной модели (`customizable-model`) в поле "Model Name" можно ввести либо короткое имя (`yandexgpt-5.1`), либо сразу готовый URI (`gpt://<folder_id>/yandexgpt-lite/latest@<суффикс>` — например, для дообученной модели).

## Проверено живым ключом (2026-08-17)

- **Базовый chat completions** — работает (`yandexgpt-lite`, ответ корректный).
- **Tool-calling (function calling), non-stream и stream** — работает надёжно на всех проверенных моделях: и вызов тула (`tool_calls` с валидным JSON в `arguments`), и обработка результата (`role: tool` → связный финальный ответ). Проверено и на простых примерах, и на реальной многоходовой истории с системным промптом ИБ-агента (`search_npa`/`search_bestpractices`) — воспроизвести "модель описывает вызов тула текстом вместо настоящего tool_call" (баг, замеченный в реальном чате Arkady) через прямой API не удалось ни разу за несколько попыток; вероятнее всего разовая случайность семплирования модели, а не системная проблема плагина/SDK.
- **Vision (изображения)** — эмпирически проверено на всех 9 моделях каталога (base64 PNG в `image_url`, живой ключ). Поддерживает только **`qwen3.6-35b-a3b`** (реально анализирует картинку). Остальные 8 — либо честно отвечают "не вижу изображение", либо падают структурной ошибкой (`qwen3-235b-a22b-fp8`: `"is not a multimodal model"`). `features: vision` выставлена только у `qwen3.6-35b-a3b.yaml`.
- **`reasoning_content`** — модели каталога (минимум `qwen3.6-35b-a3b`, `deepseek-v4-flash`, `gpt-oss-120b/20b`) реально возвращают отдельное поле `reasoning_content` в ответе (не `<think>`-обёртку внутри `content`). Base-класс SDK (`OAICompatLargeLanguageModel`) умеет стримить его через `_wrap_thinking_by_reasoning_content` — worked as-is в тестах, отдельного форка под Yandex не потребовалось.

## Известные ограничения / не проверено

- `top_p` / `frequency_penalty` / `presence_penalty` **намеренно не выставлены** в parameter_rules — официальный SDK (`ChatModelConfig`) не документирует их как поддерживаемые поля тела запроса; отправка неизвестных полей может дать `400` у строгих бэкендов.
- `user_identity_support` по умолчанию `no_support` (топ-уровневый параметр `user` не отправляется) — не подтверждено, принимает ли Yandex этот параметр.
- Каталог моделей (9 штук) может быть неполным — консоль `aistudio.yandex.ru` мог показывать больше моделей на момент сборки, доки и SDK-репозиторий не дают независимого полного списка (капча + нет каталога в коде SDK). Если видите в консоли модель не из этого списка — добавляйте по тому же шаблону, с эмпирической проверкой tool-call/vision через живой ключ (доки не источник истины, см. выше).
