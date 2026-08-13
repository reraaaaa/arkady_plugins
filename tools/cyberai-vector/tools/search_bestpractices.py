from collections.abc import Generator
from typing import Any

from arkady_plugin import Tool
from arkady_plugin.entities.tool import ToolInvokeMessage

from ._client import CyberAIError, format_records, search


class SearchBestpracticesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        query = (tool_parameters.get("query") or "").strip()
        if not query:
            yield self.create_text_message("Пустой запрос.")
            return
        base_url = (self.runtime.credentials.get("base_url") or "").rstrip("/")
        top_k = int(tool_parameters.get("top_k") or 6)
        try:
            records = search(base_url, "/bestpractices/retrieval", query, top_k)
        except CyberAIError as e:
            yield self.create_text_message(str(e))
            return
        if not records:
            yield self.create_text_message(
                "В библиотеке лучших практик не нашлось релевантных материалов.")
            return
        yield self.create_text_message(format_records(records))
