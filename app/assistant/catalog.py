"""The providers and models the help assistant can be set to. No model imports: the settings model uses this."""

PROVIDER_CHOICES: list[tuple[str, str]] = [
    ("claude", "Claude (Anthropic)"),
    ("gemini", "Gemini (Google)"),
    ("groq", "Groq"),
]

# provider -> [(model id, label)]
MODELS: dict[str, list[tuple[str, str]]] = {
    "claude": [
        ("claude-haiku-5-5", "Claude Haiku 5.5 (хурдан, хямд)"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ("claude-opus-5-5", "Claude Opus 5.5"),
        ("claude-fable-5-1", "Claude Fable 5.1"),
    ],
    "gemini": [
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite"),
        ("gemini-2.5-pro", "Gemini 2.5 Pro"),
    ],
    "groq": [
        ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
        ("llama-3.1-8b-instant", "Llama 3.1 8B"),
    ],
}

TIMEOUT_MIN = 3
TIMEOUT_MAX = 60
DEFAULT_TIMEOUT = 15
