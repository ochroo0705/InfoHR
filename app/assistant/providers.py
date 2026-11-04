"""Provider adapters for the help assistant: one question and the allowed entries in, one Choice out."""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings

from assistant.entries import HelpEntry
from assistant.prompt import (
    JSON_REPLY,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    entries_block,
    question_block,
    refusals_block,
)

logger = logging.getLogger(__name__)

_FIELDS = ("entry", "also", "lead")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass(frozen=True)
class Choice:
    entry: str  # "" = none
    also: str  # "" = none
    lead: str


class ProviderError(Exception):
    """The provider call failed or its reply is not a valid choice."""


class Provider(Protocol):
    name: str
    model: str

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice: ...


def _to_choice(data: Any) -> Choice:
    """Check that a parsed reply has the three string fields, then build the Choice."""
    if not isinstance(data, dict) or not all(isinstance(data.get(f), str) for f in _FIELDS):
        raise ProviderError("the model reply does not match the schema")
    return Choice(entry=data["entry"], also=data["also"], lead=data["lead"])


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int, client: Any | None = None) -> None:
        self.model = model
        if client is None:
            # Lazy on purpose: is_enabled() runs on every palette search and must not need the SDK.
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout * 1000))
            except Exception as exc:  # missing SDK or a bad client setup
                raise ProviderError("the Gemini client could not be created") from exc
        self._client = client

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=question_block(question),
                config={
                    "system_instruction": SYSTEM_INSTRUCTION + entries_block(entries) + refusals_block(refusals),
                    "response_mime_type": "application/json",
                    "response_schema": RESPONSE_SCHEMA,
                    "temperature": 0,
                },
            )
            data = json.loads(response.text or "")
        except Exception as exc:  # any SDK or parse failure becomes one provider error
            raise ProviderError("the model call failed") from exc
        return _to_choice(data)


def _http_post(url: str, body: bytes, headers: dict[str, str], timeout: int) -> bytes:
    """One HTTPS POST; returns the response body."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 fixed https URL
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return bytes(resp.read())


class GroqProvider:
    """Groq's OpenAI-compatible chat API, in JSON mode. Uses only the standard library."""

    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int,
        post: Callable[[str, bytes, dict[str, str], int], bytes] | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._post = post if post is not None else _http_post

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        system = SYSTEM_INSTRUCTION + entries_block(entries) + refusals_block(refusals) + "\n" + JSON_REPLY
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question_block(question)},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
            "User-Agent": "InfoHR-assistant/1",
        }
        try:
            reply = self._post(GROQ_URL, body, headers, self._timeout)
            content = json.loads(reply)["choices"][0]["message"]["content"]
            data = json.loads(content)
        # from None: the original error may hold the Authorization header, so it is not chained into a traceback.
        except urllib.error.HTTPError as exc:  # the status code helps; the key and body never go in a message
            raise ProviderError(f"the model call failed (HTTP {exc.code})") from None
        except Exception:  # network, timeout or a bad reply becomes one provider error
            raise ProviderError("the model call failed") from None
        return _to_choice(data)


def is_enabled() -> bool:
    """True when the assistant is switched on and fully configured."""
    return (
        settings.ASSISTANT_PROVIDER in ("gemini", "groq")
        and bool(settings.ASSISTANT_API_KEY)
        and bool(settings.ASSISTANT_MODEL)
    )


def get_provider() -> Provider | None:
    """The configured provider, or None when the assistant is off."""
    if not is_enabled():
        return None
    try:
        if settings.ASSISTANT_PROVIDER == "groq":
            return GroqProvider(
                api_key=settings.ASSISTANT_API_KEY,
                model=settings.ASSISTANT_MODEL,
                timeout=settings.ASSISTANT_TIMEOUT,
            )
        return GeminiProvider(
            api_key=settings.ASSISTANT_API_KEY,
            model=settings.ASSISTANT_MODEL,
            timeout=settings.ASSISTANT_TIMEOUT,
        )
    except ProviderError:
        logger.warning("The help assistant is off: the provider could not start.", exc_info=True)
        return None
