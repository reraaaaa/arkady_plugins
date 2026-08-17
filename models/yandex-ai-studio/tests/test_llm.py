"""Юнит-тесты на _prepared_credentials — единственную кастомную логику плагина
(живым ключом Yandex AI Studio не проверено, тестовых credentials нет)."""

import pytest

from models.llm.llm import YandexAIStudioLargeLanguageModel


@pytest.fixture
def model() -> YandexAIStudioLargeLanguageModel:
    return YandexAIStudioLargeLanguageModel.__new__(YandexAIStudioLargeLanguageModel)


def test_api_key_moves_to_extra_headers_as_api_key_scheme(model):
    prepped = model._prepared_credentials(
        "yandexgpt-5.1", {"api_key": "secret-key", "folder_id": "b1gfolder"}
    )
    assert prepped["extra_headers"]["Authorization"] == "Api-Key secret-key"
    # api_key НЕ должен остаться в credentials — иначе base-класс перезапишет
    # заголовок на "Bearer secret-key" (см. docstring llm.py).
    assert "api_key" not in prepped


def test_short_model_name_gets_wrapped_with_folder_id(model):
    prepped = model._prepared_credentials(
        "yandexgpt-5.1", {"api_key": "k", "folder_id": "b1gfolder"}
    )
    assert prepped["endpoint_model_name"] == "gpt://b1gfolder/yandexgpt-5.1"


def test_full_uri_model_name_is_left_untouched(model):
    prepped = model._prepared_credentials(
        "gpt://b1gother/yandexgpt-lite/latest@ft123",
        {"api_key": "k", "folder_id": "b1gfolder"},
    )
    assert prepped["endpoint_model_name"] == "gpt://b1gother/yandexgpt-lite/latest@ft123"


def test_missing_folder_id_raises_for_short_model_name(model):
    with pytest.raises(ValueError, match="Folder ID"):
        model._prepared_credentials("yandexgpt-5.1", {"api_key": "k"})


def test_default_endpoint_url_is_filled_when_missing(model):
    prepped = model._prepared_credentials(
        "yandexgpt-5.1", {"api_key": "k", "folder_id": "b1gfolder"}
    )
    assert prepped["endpoint_url"] == "https://llm.api.cloud.yandex.net/v1"


def test_explicit_endpoint_url_is_preserved(model):
    prepped = model._prepared_credentials(
        "yandexgpt-5.1",
        {"api_key": "k", "folder_id": "b1gfolder", "endpoint_url": "https://custom/v1"},
    )
    assert prepped["endpoint_url"] == "https://custom/v1"


def test_mode_defaults_to_chat(model):
    prepped = model._prepared_credentials(
        "yandexgpt-5.1", {"api_key": "k", "folder_id": "b1gfolder"}
    )
    assert prepped["mode"] == "chat"


def test_existing_extra_headers_are_preserved_alongside_authorization(model):
    prepped = model._prepared_credentials(
        "yandexgpt-5.1",
        {
            "api_key": "k",
            "folder_id": "b1gfolder",
            "extra_headers": {"X-Custom": "1"},
        },
    )
    assert prepped["extra_headers"]["X-Custom"] == "1"
    assert prepped["extra_headers"]["Authorization"] == "Api-Key k"
