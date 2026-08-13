from typing import Any

import requests
from arkady_plugin import ToolProvider
from arkady_plugin.errors.tool import ToolProviderCredentialValidationError


class CyberaiVectorProvider(ToolProvider):

    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        base_url = (credentials.get("base_url") or "").rstrip("/")
        if not base_url:
            raise ToolProviderCredentialValidationError("base_url обязателен")
        try:
            resp = requests.get(f"{base_url}/health", timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ToolProviderCredentialValidationError(
                f"Не удалось достучаться до {base_url}/health: {e}"
            ) from e
