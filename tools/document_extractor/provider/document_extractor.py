from arkady_plugin import ToolProvider


class ArkadyExtractorProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, object]) -> None:
        """The extractor has no provider credentials to validate."""
        return None
