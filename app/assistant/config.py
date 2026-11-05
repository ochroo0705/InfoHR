"""The assistant's live configuration: the admin console row when it exists, else the .env values."""

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class AssistantConfig:
    provider: str  # "" = off
    api_key: str
    model: str
    timeout: int


def from_env() -> AssistantConfig:
    return AssistantConfig(
        provider=settings.ASSISTANT_PROVIDER,
        api_key=settings.ASSISTANT_API_KEY,
        model=settings.ASSISTANT_MODEL,
        timeout=settings.ASSISTANT_TIMEOUT,
    )


def current() -> AssistantConfig:
    """Read on every call (a palette search asks), so a change in the admin console applies at once.
    Once the admin console row is saved it is the only source; .env is the starting values until then."""
    from assistant.models import AssistantSettings

    row = AssistantSettings.objects.filter(pk=1).first()
    if row is None:
        return from_env()
    return AssistantConfig(row.provider, row.api_key, row.model, row.timeout)
