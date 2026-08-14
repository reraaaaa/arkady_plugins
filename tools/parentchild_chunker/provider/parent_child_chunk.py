from typing import Any

from arkady_plugin import ToolProvider
from arkady_plugin.errors.tool import ToolProviderCredentialValidationError


class ParentChildChunkProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            """
            IMPLEMENT YOUR VALIDATION HERE
            """
        except Exception as e:
            raise ToolProviderCredentialValidationError(str(e))
