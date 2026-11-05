"""The «Холболт шалгах» button on the settings page: one tiny real call with the values on the form."""

import time
from typing import Any

from assistant.config import AssistantConfig
from assistant.entries import ENTRIES
from assistant.providers import ProviderError, build_provider


def check_connection(values: dict[str, Any]) -> tuple[bool, str]:
    """(worked, message in Mongolian). The message carries the provider's own reason when the call fails."""
    cfg = AssistantConfig(values["provider"], values["api_key"], values["model"], values["timeout"])
    if not cfg.provider:
        return False, "Үйлчилгээ үзүүлэгч сонгоогүй байна (туслах унтарсан)."
    provider = build_provider(cfg)
    if provider is None:
        return False, "Үйлчилгээ үзүүлэгчийг эхлүүлж чадсангүй. Түлхүүр, загвараа шалгана уу."
    started = time.monotonic()
    try:
        provider.choose("ажилтан хэрхэн бүртгэх вэ", ENTRIES[:1])
    except ProviderError as exc:
        return False, f"Холбогдсонгүй: {exc}"
    except Exception as exc:  # the button must always answer, whatever the adapter raised
        return False, f"Холбогдсонгүй: {type(exc).__name__}"
    return True, f"Холбогдлоо ({int((time.monotonic() - started) * 1000)} мс)."
