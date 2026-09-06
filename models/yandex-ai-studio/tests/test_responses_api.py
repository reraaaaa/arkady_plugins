"""Юнит-тесты на конвертацию Dify PromptMessage <-> Yandex Responses API.

Сетевые вызовы не мокаются намеренно — формат SSE и output-items здесь
подобраны по живым HTTP-ответам (проверено вручную 2026-09, доки на
aistudio.yandex.ru блокируют капчей ботов), тестируем только чистую логику
преобразования без сети.
"""

import pytest

from models.llm.llm import YandexAIStudioLargeLanguageModel

pytest.importorskip("arkady_plugin")

from arkady_plugin.entities.model.message import (
    AssistantPromptMessage,
    SystemPromptMessage,
    ToolPromptMessage,
    UserPromptMessage,
)


@pytest.fixture
def model() -> YandexAIStudioLargeLanguageModel:
    return YandexAIStudioLargeLanguageModel.__new__(YandexAIStudioLargeLanguageModel)


def test_system_message_becomes_instructions_not_input_item(model):
    instructions, input_items = model._to_responses_input([
        SystemPromptMessage(content="Ты эксперт по ИБ."),
        UserPromptMessage(content="Привет"),
    ])
    assert instructions == "Ты эксперт по ИБ."
    assert input_items == [{"role": "user", "content": "Привет"}]


def test_multiple_system_messages_are_joined(model):
    instructions, _ = model._to_responses_input([
        SystemPromptMessage(content="Первое правило."),
        SystemPromptMessage(content="Второе правило."),
    ])
    assert instructions == "Первое правило.\n\nВторое правило."


def test_no_system_message_gives_none_instructions(model):
    instructions, _ = model._to_responses_input([UserPromptMessage(content="привет")])
    assert instructions is None


def test_assistant_tool_call_becomes_function_call_item(model):
    tool_call = AssistantPromptMessage.ToolCall(
        id="call_123",
        type="function",
        function=AssistantPromptMessage.ToolCall.ToolCallFunction(
            name="search_npa", arguments='{"query": "К1"}',
        ),
    )
    _, input_items = model._to_responses_input([
        UserPromptMessage(content="ищи"),
        AssistantPromptMessage(content=None, tool_calls=[tool_call]),
    ])
    assert input_items[-1] == {
        "type": "function_call",
        "call_id": "call_123",
        "name": "search_npa",
        "arguments": '{"query": "К1"}',
    }


def test_assistant_text_and_tool_call_both_kept_in_order(model):
    tool_call = AssistantPromptMessage.ToolCall(
        id="call_1",
        type="function",
        function=AssistantPromptMessage.ToolCall.ToolCallFunction(name="search_npa", arguments="{}"),
    )
    _, input_items = model._to_responses_input([
        AssistantPromptMessage(content="Ищу...", tool_calls=[tool_call]),
    ])
    assert input_items[0] == {"role": "assistant", "content": "Ищу..."}
    assert input_items[1]["type"] == "function_call"


def test_tool_result_becomes_function_call_output(model):
    _, input_items = model._to_responses_input([
        ToolPromptMessage(content="[найдено 3 фрагмента]", tool_call_id="call_123"),
    ])
    assert input_items == [{
        "type": "function_call_output",
        "call_id": "call_123",
        "output": "[найдено 3 фрагмента]",
    }]


def test_tools_flattened_without_nested_function_object(model):
    from arkady_plugin.entities.model.message import PromptMessageTool

    tools = model._to_responses_tools([
        PromptMessageTool(
            name="search_npa",
            description="Ищет по НПА",
            parameters={"type": "object", "properties": {}},
        ),
    ])
    assert tools == [{
        "type": "function",
        "name": "search_npa",
        "description": "Ищет по НПА",
        "parameters": {"type": "object", "properties": {}},
    }]


def test_output_item_to_tool_call_dict_prefers_call_id_over_id(model):
    item = {
        "id": "internal-item-id",
        "call_id": "000_abc",
        "name": "search_npa",
        "arguments": '{"query":"К1"}',
        "type": "function_call",
    }
    result = model._output_item_to_tool_call_dict(item)
    assert result == {
        "id": "000_abc",
        "type": "function",
        "function": {"name": "search_npa", "arguments": '{"query":"К1"}'},
    }


def _stub_calc_response_usage(monkeypatch, model):
    # _calc_response_usage (base-класс) считает цену через
    # get_model_schema()/model_schemas, которые заполняются только при
    # полной инициализации провайдера — в юнит-тесте (__new__) их нет.
    # Подменяем на эхо входных token-counts, чтобы проверять именно нашу
    # конвертацию input_tokens/output_tokens -> usage, а не прайсинг.
    from arkady_plugin.entities.model.llm import LLMUsage

    def fake(_model, _credentials, prompt_tokens, completion_tokens):
        usage = LLMUsage.empty_usage()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        return usage

    monkeypatch.setattr(model, "_calc_response_usage", fake)


def test_handle_responses_result_extracts_text_and_tool_calls(model, monkeypatch):
    _stub_calc_response_usage(monkeypatch, model)
    response_json = {
        "model": "gpt://folder/yandexgpt-5.1",
        "output": [
            {
                "type": "function_call",
                "call_id": "000_x",
                "name": "search_npa",
                "arguments": '{"query":"К1"}',
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    result = model._handle_responses_result(
        "yandexgpt-5.1",
        {},
        response_json,
        [UserPromptMessage(content="вопрос")],
    )
    assert result.message.content == ""
    assert len(result.message.tool_calls) == 1
    assert result.message.tool_calls[0].function.name == "search_npa"
    assert result.usage.prompt_tokens == 100
    assert result.usage.completion_tokens == 20


def test_handle_responses_result_extracts_plain_text_message(model, monkeypatch):
    _stub_calc_response_usage(monkeypatch, model)
    response_json = {
        "model": "gpt://folder/yandexgpt-5.1",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Уточните запрос."}],
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = model._handle_responses_result(
        "yandexgpt-5.1",
        {},
        response_json,
        [UserPromptMessage(content="вопрос")],
    )
    assert result.message.content == "Уточните запрос."
    assert result.message.tool_calls == []


def test_handle_responses_result_raises_on_error(model):
    from arkady_plugin.errors.model import InvokeError

    with pytest.raises(InvokeError):
        model._handle_responses_result(
            "yandexgpt-5.1",
            {},
            {"error": {"message": "bad request"}},
            [UserPromptMessage(content="вопрос")],
        )
