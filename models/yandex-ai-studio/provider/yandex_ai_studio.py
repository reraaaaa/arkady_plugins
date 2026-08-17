import logging

from arkady_plugin import ModelProvider
from arkady_plugin.entities.model import ModelType
from arkady_plugin.errors.model import CredentialsValidateFailedError

logger = logging.getLogger(__name__)


class YandexAIStudioProvider(ModelProvider):
    def validate_provider_credentials(self, credentials: dict) -> None:
        """
        Validate provider credentials

        if validate failed, raise exception

        :param credentials: provider credentials, credentials form defined in `provider_credential_schema`.
        """
        try:
            model_instance = self.get_model_instance(ModelType.LLM)
            model_instance.validate_credentials(model="yandexgpt-5.1", credentials=credentials)
        except CredentialsValidateFailedError:
            raise
        except Exception:
            logger.exception(f"{self.get_provider_schema().provider} credentials validate failed")
            raise
