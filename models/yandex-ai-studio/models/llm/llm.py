# ruff: noqa: I001
# arkady_plugin ДОЛЖЕН импортироваться первым: пакет патчит ssl/socket
# через gevent.monkey.patch_all() как side-effect своего __init__
# (arkady_plugin/_gevent.py) — это обязано случиться раньше, чем что-либо
# успеет импортировать `requests`/`ssl` само по себе, иначе получаем
# RecursionError в urllib3 (несовместимые patched/unpatched SSLContext).
# Порядок импортов ниже сознательно не отсортирован — не давать ruff/isort
# его "починить".
from arkady_plugin.interfaces.model.openai_compatible.llm import (
    OAICompatLargeLanguageModel,
)

import json
from collections.abc import Generator
from http import HTTPStatus

import requests
from arkady_plugin.config.config import ArkadyPluginEnv
from arkady_plugin.entities.model.llm import LLMResult, LLMResultChunk, LLMResultChunkDelta
from arkady_plugin.entities.model.message import (
    AssistantPromptMessage,
    PromptMessage,
    PromptMessageContentType,
    PromptMessageTool,
    SystemPromptMessage,
    ToolPromptMessage,
    UserPromptMessage,
)
from arkady_plugin.errors.model import InvokeError

_plugin_config = ArkadyPluginEnv()


class YandexAIStudioLargeLanguageModel(OAICompatLargeLanguageModel):
    """Yandex AI Studio отдаёт OpenAI-совместимый REST (то же тело/ответ, что и
    generic openai-совместимый провайдер) — поэтому вся сетевая логика взята
    как есть из OAICompatLargeLanguageModel (arkady-plugin-sdk), без форка
    generic openai-api-compatible плагина (там 700+ строк костылей под чужие
    шлюзы — LiteLLM-ретраи, thinking-mode, web-search-форматы, — не имеющих
    отношения к Yandex).

    Два реальных отличия от generic OpenAI-совместимого провайдера, которые
    base-класс сам не умеет:

    1. Заголовок авторизации — "Authorization: Api-Key <ключ>", а не Bearer.
       Подтверждено по исходникам офиц. SDK (github.com/yandex-cloud/
       yandex-ai-studio-sdk, _auth.py: APIKeyAuth.get_auth_metadata →
       ('authorization', f'Api-Key {key}')) — доки на aistudio.yandex.ru
       отдают капчу ботам, поэтому источник истины — код SDK, не сайт.
       Base-класс (_generate/_request_credentials_validation) собирает
       заголовки как `{**base, **extra_headers}`, а ЗАТЕМ, если
       credentials["api_key"] непусто, перезаписывает Authorization на
       "Bearer <api_key>" — то есть наш заголовок из extra_headers он бы
       затёр. Поэтому здесь реальный ключ уходит в extra_headers, а
       credentials["api_key"] перед вызовом super() зануляется, чтобы
       веткa "if api_key: ... Bearer" не сработала.
    2. Модель адресуется URI "gpt://<folder_id>/<model>", а не голым именем.
       Base-класс уже умеет слать другое имя "по проводу", чем показано в UI
       (credentials["endpoint_model_name"], читается вместо `model`) — этим
       же механизмом собираем URI, вместо изобретения нового поля.

    Третье, необязательное отличие — выбор API (credentials["api_mode"]):

    - "chat_completions" (по умолчанию) — как раньше, через base-класс,
      POST на {endpoint_url}/chat/completions.
    - "responses_api" — свой собственный клиент ниже, POST на Yandex'овский
      Responses API (rest-assistant.api.cloud.yandex.net/v1/responses,
      структурно 1:1 повторяет OpenAI Responses API: input/output items
      вместо messages/choices, function_call/function_call_output вместо
      tool_calls/role=tool). Причина существования: с этим провайдером
      замечено, что при auto tool_choice через chat/completions модель
      иногда описывает намерение вызвать инструмент ТЕКСТОМ
      ("[search_npa] запрос...", "search_npa(\"запрос\")") вместо
      настоящего structured tool_call — воспроизводится нестабильно
      (вероятностно, не поймано ни разу за 40+ офлайн-прогонов ни на
      chat/completions, ни на Responses API в одинаковых условиях), но
      наблюдается живьём в Arkady. Доки Yandex прямо говорят, что
      автоматический вызов инструментов — это Responses API, а
      chat/completions лишь "OpenAI-совместимый" в смысле формата, не
      обязательно с той же дисциплиной function calling. Переключатель
      добавлен, чтобы это можно было сравнить на реальном трафике, не
      теряя возможности откатиться на проверенный путь без переустановки
      плагина.
    """

    _DEFAULT_ENDPOINT_URL = "https://llm.api.cloud.yandex.net/v1"
    _RESPONSES_API_URL = "https://rest-assistant.api.cloud.yandex.net/v1/responses"

    def _prepared_credentials(self, model: str, credentials: dict) -> dict:
        c = dict(credentials)
        c.setdefault("mode", "chat")
        if not c.get("endpoint_url"):
            c["endpoint_url"] = self._DEFAULT_ENDPOINT_URL

        real_key = c.pop("api_key", "") or ""
        extra_headers = dict(c.get("extra_headers") or {})
        if real_key:
            extra_headers["Authorization"] = f"Api-Key {real_key}"
        c["extra_headers"] = extra_headers
        # c["api_key"] сознательно не восстанавливаем — см. docstring класса.

        endpoint_model = c.get("endpoint_model_name") or model
        if "://" not in endpoint_model:
            folder_id = c.get("folder_id", "")
            if not folder_id:
                msg = (
                    "Не задан Folder ID — без него нельзя собрать модель Yandex "
                    "'gpt://<folder_id>/<модель>'. Либо укажи Folder ID в "
                    "настройках провайдера, либо впиши в поле модели готовый "
                    "URI вида gpt://<folder_id>/<model>."
                )
                raise ValueError(msg)
            endpoint_model = f"gpt://{folder_id}/{endpoint_model}"
        c["endpoint_model_name"] = endpoint_model

        return c

    def _generate(self, model, credentials, *args, **kwargs):
        return super()._generate(model, self._prepared_credentials(model, credentials), *args, **kwargs)

    def _request_credentials_validation(self, model, credentials):
        return super()._request_credentials_validation(model, self._prepared_credentials(model, credentials))

    def _invoke(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        if credentials.get("api_mode") == "responses_api":
            return self._invoke_responses_api(
                model,
                self._prepared_credentials(model, credentials),
                prompt_messages,
                model_parameters,
                tools,
                stream,
                user,
            )
        # chat_completions (дефолт) — не трогаем прежний путь вообще,
        # включая его собственную подготовку credentials внутри _generate.
        return super()._invoke(
            model, credentials, prompt_messages, model_parameters, tools, stop, stream, user,
        )

    # ------------------------------------------------------------------
    # Responses API — отдельный клиент (другой формат запроса/ответа, не
    # переиспользует _generate/_handle_generate_* base-класса).
    # ------------------------------------------------------------------

    @staticmethod
    def _to_responses_input(
        prompt_messages: list[PromptMessage],
    ) -> tuple[str | None, list[dict]]:
        """История Dify (PromptMessage) → (instructions, input) Responses API.

        Responses API не знает system-роли в input — системный промпт уходит
        отдельным полем instructions. Результат вызова тула — не
        role="tool"-сообщение, а отдельный элемент function_call_output,
        привязанный к call_id соответствующего элемента function_call.
        """
        instructions_parts: list[str] = []
        input_items: list[dict] = []
        for message in prompt_messages:
            if isinstance(message, SystemPromptMessage):
                if isinstance(message.content, str) and message.content:
                    instructions_parts.append(message.content)
            elif isinstance(message, UserPromptMessage):
                if isinstance(message.content, str):
                    input_items.append({"role": "user", "content": message.content})
                else:
                    parts = []
                    for content in message.content or []:
                        if content.type == PromptMessageContentType.TEXT:
                            parts.append({"type": "input_text", "text": content.data})
                        elif content.type == PromptMessageContentType.IMAGE:
                            parts.append({"type": "input_image", "image_url": content.data})
                    input_items.append({"role": "user", "content": parts})
            elif isinstance(message, AssistantPromptMessage):
                if message.content:
                    input_items.append({"role": "assistant", "content": message.content})
                for tool_call in message.tool_calls or []:
                    input_items.append({
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    })
            elif isinstance(message, ToolPromptMessage):
                content = message.content
                output = content if isinstance(content, str) else json.dumps(
                    content, ensure_ascii=False,
                )
                input_items.append({
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": output,
                })
        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, input_items

    @staticmethod
    def _to_responses_tools(tools: list[PromptMessageTool] | None) -> list[dict]:
        # Плоская структура (type/name/description/parameters), БЕЗ
        # вложенного "function"-объекта — в отличие от Chat Completions
        # (PromptMessageFunction). Подтверждено живым запросом.
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.parameters,
            }
            for tool in (tools or [])
        ]

    @staticmethod
    def _output_item_to_tool_call_dict(item: dict) -> dict:
        # Приводим output-item Responses API к форме Chat Completions
        # tool_call, чтобы переиспользовать готовый
        # _extract_response_tool_calls базового класса.
        return {
            "id": item.get("call_id") or item.get("id", ""),
            "type": "function",
            "function": {
                "name": item.get("name", ""),
                "arguments": item.get("arguments", ""),
            },
        }

    def _invoke_responses_api(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None,
        stream: bool,
        user: str | None,
    ) -> LLMResult | Generator:
        instructions, input_items = self._to_responses_input(prompt_messages)

        body: dict = dict(model_parameters)
        # response_format в Chat Completions — {"type": ...}; у Responses
        # API для этого другая, недокументированная (капча блокирует доки)
        # форма (text.format) — не рискуем угадывать, просто не шлём.
        body.pop("response_format", None)
        if "max_tokens" in body:
            body["max_output_tokens"] = body.pop("max_tokens")
        tool_choice = body.pop("tool_choice", "auto")

        body["model"] = credentials.get("endpoint_model_name", model)
        body["input"] = input_items
        body["stream"] = stream
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = self._to_responses_tools(tools)
            body.setdefault("tool_choice", tool_choice)
        if user and credentials.get("user_identity_support") == "support":
            body["user"] = user

        headers = {
            "Content-Type": "application/json",
            **(credentials.get("extra_headers") or {}),
        }
        response = requests.post(
            self._RESPONSES_API_URL,
            headers=headers,
            data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode(
                "utf-8", "backslashreplace",
            ),
            timeout=(10, _plugin_config.MAX_REQUEST_TIMEOUT),
            stream=stream,
        )
        if response.encoding is None or response.encoding == "ISO-8859-1":
            response.encoding = "utf-8"
        if response.status_code != HTTPStatus.OK:
            msg = (
                "Responses API request failed with status code "
                f"{response.status_code}: {response.text}"
            )
            raise InvokeError(msg)

        if stream:
            return self._handle_responses_stream_response(
                model, credentials, response, prompt_messages,
            )
        return self._handle_responses_result(
            model, credentials, response.json(), prompt_messages,
        )

    def _handle_responses_result(
        self,
        model: str,
        credentials: dict,
        response_json: dict,
        prompt_messages: list[PromptMessage],
    ) -> LLMResult:
        if response_json.get("error"):
            msg = f"Yandex Responses API вернул ошибку: {response_json['error']}"
            raise InvokeError(msg)

        text_parts: list[str] = []
        tool_call_dicts: list[dict] = []
        for item in response_json.get("output", []):
            item_type = item.get("type")
            if item_type == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))
            elif item_type == "function_call":
                tool_call_dicts.append(self._output_item_to_tool_call_dict(item))

        assistant_message = AssistantPromptMessage(
            content="".join(text_parts),
            tool_calls=self._extract_response_tool_calls(tool_call_dicts),
        )

        usage_raw = response_json.get("usage") or {}
        prompt_tokens = usage_raw.get("input_tokens")
        completion_tokens = usage_raw.get("output_tokens")
        if prompt_tokens is None:
            prompt_tokens = self._num_tokens_from_string(prompt_messages[0].content or "")
        if completion_tokens is None:
            completion_tokens = self._num_tokens_from_string(assistant_message.content or "")
        usage = self._calc_response_usage(model, credentials, prompt_tokens, completion_tokens)

        return LLMResult(
            model=response_json.get("model", model),
            message=assistant_message,
            usage=usage,
        )

    def _handle_responses_stream_response(
        self,
        model: str,
        credentials: dict,
        response: requests.Response,
        prompt_messages: list[PromptMessage],
    ) -> Generator:
        """Разобрать SSE Responses API.

        Формат живой (проверено 2026-09 напрямую HTTP-запросом — доки на
        aistudio.yandex.ru блокируют капчей ботов, источника лучше нет):
        каждое SSE-сообщение — строка `data:{...}` СРАЗУ ЗА КОТОРОЙ строка
        `event:<имя>` (в этом порядке, data перед event — не как в
        примерах OpenAI, где принято сначала event). Итоговый function_call
        приходит ЦЕЛИКОМ одним куском в событии response.completed
        (там response.output уже полностью собран) — Yandex не дробит
        function-call-аргументы на дельты по несколько токенов, как это
        иногда делает OpenAI. Поэтому, в отличие от Chat Completions
        (_handle_generate_stream_response, копящего tool_calls по
        output_index), здесь не нужна ручная сборка по индексам: копим
        только текстовые дельты (для эффекта печати), а tool_calls и usage
        берём из финального полного снимка.
        """
        chunk_index = 0
        full_content = ""
        pending_data: dict | None = None
        final_response: dict | None = None

        for raw_line in response.iter_lines(decode_unicode=True):
            line = raw_line.strip() if raw_line else ""
            if not line:
                continue
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload:
                    try:
                        pending_data = json.loads(payload)
                    except json.JSONDecodeError:
                        pending_data = None
                continue
            if not line.startswith("event:") or pending_data is None:
                continue
            event_name = line[len("event:"):].strip()
            data = pending_data
            pending_data = None

            if event_name == "response.output_text.delta":
                delta = data.get("delta", "")
                if not delta:
                    continue
                full_content += delta
                chunk_index += 1
                yield LLMResultChunk(
                    model=model,
                    delta=LLMResultChunkDelta(
                        index=chunk_index,
                        message=AssistantPromptMessage(content=delta),
                    ),
                )
            elif event_name in ("response.completed", "response.incomplete"):
                final_response = data.get("response") or {}
            elif event_name == "response.failed":
                error = (data.get("response") or {}).get("error") or data
                msg = f"Yandex Responses API вернул ошибку в стриме: {error}"
                raise InvokeError(msg)

        if final_response is None:
            msg = "Yandex Responses API: поток завершился без response.completed"
            raise InvokeError(msg)
        if final_response.get("error"):
            msg = f"Yandex Responses API вернул ошибку: {final_response['error']}"
            raise InvokeError(msg)

        tool_call_dicts = [
            self._output_item_to_tool_call_dict(item)
            for item in final_response.get("output", [])
            if item.get("type") == "function_call"
        ]
        tool_calls = self._extract_response_tool_calls(tool_call_dicts)

        finish_reason = "tool_calls" if tool_calls else "stop"
        if final_response.get("status") == "incomplete":
            finish_reason = (final_response.get("incomplete_details") or {}).get(
                "reason", "incomplete",
            )

        if tool_calls:
            chunk_index += 1
            yield LLMResultChunk(
                model=model,
                delta=LLMResultChunkDelta(
                    index=chunk_index,
                    message=AssistantPromptMessage(tool_calls=tool_calls, content=""),
                ),
            )

        usage_raw = final_response.get("usage") or {}
        # _create_final_llm_result_chunk ждёт OpenAI-именование ключей
        # (prompt_tokens/completion_tokens), у Yandex Responses API —
        # input_tokens/output_tokens; перекладываем, иначе он молча
        # свалится на грубую gpt2-оценку вместо точных цифр из API.
        usage_for_helper = {
            "prompt_tokens": usage_raw.get("input_tokens"),
            "completion_tokens": usage_raw.get("output_tokens"),
        }

        yield self._create_final_llm_result_chunk(
            index=chunk_index,
            message=AssistantPromptMessage(content=""),
            finish_reason=finish_reason,
            usage=usage_for_helper,
            model=model,
            prompt_messages=prompt_messages,
            credentials=credentials,
            full_content=full_content,
        )
