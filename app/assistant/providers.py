"""Provider adapters for the help assistant: one question and the allowed entries in, one Choice out."""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Protocol

from assistant import config
from assistant.entries import HelpEntry
from assistant.prompt import (
    JSON_REPLY,
    PLAN_INSTRUCTION,
    PLAN_REPLY,
    PLAN_SCHEMA,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    columns_block,
    entries_block,
    plan_input,
    question_block,
    refusals_block,
    table_examples_block,
    words_block,
)
from assistant.words import FilterWords

if TYPE_CHECKING:  # assistant.plan imports ProviderError from this module, so it is imported where it is used
    from assistant.columns import RuleColumn
    from assistant.fields import AskableField
    from assistant.plan import Plan

logger = logging.getLogger(__name__)

_FIELDS = ("entry", "also", "lead")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_VERSION = "2023-06-01"

# Added to the system text when a caller passes its own schema to complete_json. Gemini enforces the schema through
# response_schema; the other adapters only get JSON mode, so they are told the shape in words.
SCHEMA_REPLY = "Reply with only one JSON object that matches this JSON schema: "


def _with_schema(system: str, schema: dict[str, Any] | None) -> str:
    """The system text with the schema appended as text. None (the default) leaves the text exactly as it is."""
    if schema is None:
        return system
    return system + "\n" + SCHEMA_REPLY + json.dumps(schema, ensure_ascii=False)


@dataclass(frozen=True)
class Choice:
    entry: str  # "" = none
    also: str  # "" = none
    lead: str


class ProviderError(Exception):
    """The provider call failed or its reply is not a valid choice."""


class _Usage:
    """Tokens a provider object has used so far: summed over its calls, read by services.answer for the log row."""

    tokens_in = 0
    tokens_out = 0

    def _add_usage(self, tokens_in: Any, tokens_out: Any) -> None:
        """Adds one reply's counts. A missing or odd value counts as 0: usage must never break an answer."""
        self.tokens_in += tokens_in if isinstance(tokens_in, int) and tokens_in > 0 else 0
        self.tokens_out += tokens_out if isinstance(tokens_out, int) and tokens_out > 0 else 0


class Provider(Protocol):
    name: str
    model: str

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice: ...

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence["AskableField"] = (),
    ) -> "Plan": ...

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any: ...


def _to_choice(data: Any) -> Choice:
    """Check that a parsed reply has the three string fields, then build the Choice."""
    if not isinstance(data, dict) or not all(isinstance(data.get(f), str) for f in _FIELDS):
        raise ProviderError("the model reply does not match the schema")
    return Choice(entry=data["entry"], also=data["also"], lead=data["lead"])


def _plan_system(
    entries: Sequence[HelpEntry],
    words: Sequence[FilterWords],
    phrases: Mapping[str, list[str]],
    refusals: Sequence[str],
    table_examples: Sequence[tuple[str, str]] = (),
    field_hints: Sequence["AskableField"] = (),
    rule_columns: Sequence["RuleColumn"] = (),
) -> str:
    """The system text for a plan: the instruction, the help entries, then the filters and fields as a JSON block,
    then the rule columns when there are any."""
    return (
        PLAN_INSTRUCTION
        + "\nHelp entries:\n"
        + entries_block(entries)
        + "\nFilters:\n"
        + words_block(words, phrases, field_hints)
        + ("\n" + columns_block(rule_columns) if rule_columns else "")
        + refusals_block(refusals)
        + table_examples_block(table_examples)
    )


MATCHES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"column": {"type": "integer"}, "field": {"type": "string"}},
                "required": ["column", "field"],
            },
        },
    },
    "required": ["matches"],
}


class GeminiProvider(_Usage):
    name = "gemini"
    takes_rules = True

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

    def _call_json(self, system: str, user: str, schema: dict[str, Any]) -> Any:
        """One generate_content call in JSON mode with the given response schema; returns the parsed reply."""
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=user,
                config={
                    "system_instruction": system,
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "temperature": 0,
                },
            )
            meta = getattr(response, "usage_metadata", None)
            self._add_usage(getattr(meta, "prompt_token_count", 0), getattr(meta, "candidates_token_count", 0))
            return json.loads(response.text or "")
        except Exception as exc:  # any SDK or parse failure becomes one provider error
            raise ProviderError(f"{type(exc).__name__}: the model call failed") from exc

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        system = SYSTEM_INSTRUCTION + entries_block(entries) + refusals_block(refusals)
        return _to_choice(self._call_json(system, question_block(question), RESPONSE_SCHEMA))

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence["AskableField"] = (),
        open_chart: tuple[str, str] | None = None,
        rule_columns: Sequence["RuleColumn"] = (),
    ) -> "Plan":
        from assistant.plan import parse_plan  # local: assistant.plan imports this module

        system = _plan_system(entries, words, phrases, refusals, table_examples, field_hints, rule_columns)
        return parse_plan(self._call_json(system, plan_input(question, today, previous, open_chart), PLAN_SCHEMA))

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        """A generic JSON call: the caller's system and user text in, the parsed reply object out. The schema is
        the response schema; None means MATCHES_SCHEMA."""
        return self._call_json(system, user, MATCHES_SCHEMA if schema is None else schema)


def _http_post(url: str, body: bytes, headers: dict[str, str], timeout: int) -> bytes:
    """One HTTPS POST; returns the response body."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 fixed https URL
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return bytes(resp.read())


class _OpenAICompatProvider(_Usage):
    """An OpenAI-compatible chat API, in JSON mode. Uses only the standard library. Subclasses set name and url."""

    name = ""
    url = ""
    takes_rules = True

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

    def _call_json(self, system: str, user: str) -> Any:
        """One chat call in JSON mode; returns the parsed reply object."""
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
            "User-Agent": "MACSHumanCapital-assistant/1",
        }
        try:
            reply = self._post(self.url, body, headers, self._timeout)
            data = json.loads(reply)
            usage = data.get("usage") if isinstance(data, dict) else None
            if isinstance(usage, dict):
                self._add_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        # from None: the original error may hold the Authorization header, so it is not chained into a traceback.
        except urllib.error.HTTPError as exc:  # the status code and the provider's message; never the key
            detail = _api_detail(exc, self._api_key)
            raise ProviderError(f"HTTP {exc.code}" + (f": {detail}" if detail else "")) from None
        except Exception as exc:  # network, timeout or a bad reply becomes one provider error
            raise ProviderError(f"{type(exc).__name__}: no usable reply") from None

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        system = SYSTEM_INSTRUCTION + entries_block(entries) + refusals_block(refusals) + "\n" + JSON_REPLY
        return _to_choice(self._call_json(system, question_block(question)))

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence["AskableField"] = (),
        open_chart: tuple[str, str] | None = None,
        rule_columns: Sequence["RuleColumn"] = (),
    ) -> "Plan":
        from assistant.plan import parse_plan  # local: assistant.plan imports this module

        system = _plan_system(entries, words, phrases, refusals, table_examples, field_hints, rule_columns)
        system += "\n" + PLAN_REPLY
        return parse_plan(self._call_json(system, plan_input(question, today, previous, open_chart)))

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        """A generic JSON call: the caller's system and user text in, the parsed reply object out. A schema is
        sent as text in the system message (JSON mode does not enforce it)."""
        return self._call_json(_with_schema(system, schema), user)


class GroqProvider(_OpenAICompatProvider):
    """Groq's chat API."""

    name = "groq"
    url = GROQ_URL


class DeepSeekProvider(_OpenAICompatProvider):
    """DeepSeek's chat API (JSON mode needs the word JSON in the prompt, which JSON_REPLY and PLAN_REPLY supply)."""

    name = "deepseek"
    url = DEEPSEEK_URL


def _api_detail(exc: urllib.error.HTTPError, api_key: str) -> str:
    """The provider's own error text (for example "invalid x-api-key"), so the admin log shows why a call failed.
    The key is blanked out of it, and anything that is not a short JSON message is dropped."""
    try:
        body = json.loads(exc.read())
        error = body["error"]
        message = error["message"] if isinstance(error, dict) else str(error)
    except Exception:
        return ""
    return str(message).replace(api_key, "***")[:200]


class ClaudeProvider(_Usage):
    """Anthropic's Messages API. Uses only the standard library, like Groq."""

    name = "claude"
    takes_rules = True

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

    def _call_json(self, system: str, user: str, max_tokens: int) -> Any:
        """One Messages call; returns the JSON object found in the text reply."""
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": max_tokens,
                # Newer models think by default, and the thinking counts against max_tokens: on a 800 limit
                # claude-haiku-5-5 used all of it, wrote no text and the SQL answer failed. These are short JSON
                # replies, so thinking is switched off.
                "thinking": {"type": "disabled"},
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": CLAUDE_VERSION,
            "content-type": "application/json",
            "User-Agent": "MACSHumanCapital-assistant/1",
        }
        try:
            reply = self._post(CLAUDE_URL, body, headers, self._timeout)
            data = json.loads(reply)
            usage = data.get("usage") if isinstance(data, dict) else None
            if isinstance(usage, dict):  # cached input is billed apart from input_tokens, so it is counted in
                cached = sum(
                    n
                    for n in (usage.get("cache_creation_input_tokens"), usage.get("cache_read_input_tokens"))
                    if isinstance(n, int)
                )
                tokens_in = usage.get("input_tokens")
                self._add_usage((tokens_in if isinstance(tokens_in, int) else 0) + cached, usage.get("output_tokens"))
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            start, end = text.find("{"), text.rfind("}")  # tolerate a sentence or a code fence around the object
            return json.loads(text[start : end + 1])
        # from None: the original error may hold the key header, so it is not chained into a traceback.
        except urllib.error.HTTPError as exc:
            detail = _api_detail(exc, self._api_key)
            raise ProviderError(f"HTTP {exc.code}" + (f": {detail}" if detail else "")) from None
        except Exception as exc:
            raise ProviderError(f"{type(exc).__name__}: no usable reply") from None

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        system = SYSTEM_INSTRUCTION + entries_block(entries) + refusals_block(refusals) + "\n" + JSON_REPLY
        return _to_choice(self._call_json(system, question_block(question), max_tokens=400))

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence["AskableField"] = (),
        open_chart: tuple[str, str] | None = None,
        rule_columns: Sequence["RuleColumn"] = (),
    ) -> "Plan":
        from assistant.plan import parse_plan  # local: assistant.plan imports this module

        # 800, not 400: a plan can hold up to MAX_PARTS parts, each with a param and a value.
        system = _plan_system(entries, words, phrases, refusals, table_examples, field_hints, rule_columns)
        system += "\n" + PLAN_REPLY
        return parse_plan(self._call_json(system, plan_input(question, today, previous, open_chart), max_tokens=800))

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        """A generic JSON call: the caller's system and user text in, the parsed reply object out. A schema is
        sent as text in the system prompt (the Messages call here has no structured-output mode)."""
        return self._call_json(_with_schema(system, schema), user, max_tokens=800)


def is_enabled() -> bool:
    """True when the assistant is switched on and fully configured."""
    cfg = config.current()
    return cfg.provider in ("claude", "deepseek", "gemini", "groq") and bool(cfg.api_key) and bool(cfg.model)


def build_provider(cfg: config.AssistantConfig) -> Provider | None:
    """The adapter for a configuration, or None when it is off, incomplete or the adapter could not start."""
    if cfg.provider not in ("claude", "deepseek", "gemini", "groq") or not cfg.api_key or not cfg.model:
        return None
    try:
        if cfg.provider == "groq":
            return GroqProvider(api_key=cfg.api_key, model=cfg.model, timeout=cfg.timeout)
        if cfg.provider == "deepseek":
            return DeepSeekProvider(api_key=cfg.api_key, model=cfg.model, timeout=cfg.timeout)
        if cfg.provider == "claude":
            return ClaudeProvider(api_key=cfg.api_key, model=cfg.model, timeout=cfg.timeout)
        return GeminiProvider(api_key=cfg.api_key, model=cfg.model, timeout=cfg.timeout)
    except ProviderError:
        logger.warning("The help assistant is off: the provider could not start.", exc_info=True)
        return None


def get_provider() -> Provider | None:
    """The configured provider, or None when the assistant is off."""
    return build_provider(config.current())
