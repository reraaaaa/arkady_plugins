import logging
from collections.abc import Mapping

from arkady_plugin import ModelProvider
from arkady_plugin.entities.model import ModelType

logger = logging.getLogger(__name__)


class OpenAIProvider(ModelProvider):
    def validate_provider_credentials(self, credentials: Mapping) -> None:
        try:
            model_instance = self.get_model_instance(ModelType.LLM)
            validate_model = credentials.get("validate_model") or "gpt-4o-mini"
            model_instance.validate_credentials(
                model=validate_model, credentials=credentials
            )
        except Exception:
            logger.exception("OpenAI credentials validation failed")
            raise
