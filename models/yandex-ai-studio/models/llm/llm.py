from arkady_plugin.interfaces.model.openai_compatible.llm import (
    OAICompatLargeLanguageModel,
)


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

    Не проверено живым ключом (нет тестовых credentials) — перед реальным
    использованием нужен смоук-тест в UI Arkady.
    """

    _DEFAULT_ENDPOINT_URL = "https://llm.api.cloud.yandex.net/v1"

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
