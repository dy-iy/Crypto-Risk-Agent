"""Context limits used by the active asynchronous model client and agents."""
from app.attackpilot.settings import LLM_NAME

MODEL_CONTEXT_WINDOWS = {
    # Preserve the workflow's existing bounded context budget.
    LLM_NAME: 128000,
    # --- OpenAI ---
    "gpt-4o": 128000,
    "gpt-4o-2024-08-06": 128000,
    "gpt-4o-mini": 128000,
    "o1-preview": 128000,
    "o1-mini": 128000,

    # --- Google Gemini ---
    "gemini-1.5-pro": 2000000,
    "gemini-1.5-flash": 1000000,
    "gemini-2.0-flash": 1000000,
    "gemini-3.0-pro": 2000000,

    # --- Xiaomi MiMo ---
    "mimo-v2.5-pro": 1048576,

    # --- Anthropic Claude ---
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-5-haiku": 200000,
    "claude-3-opus": 200000,

    # --- DeepSeek ---
    "deepseek-chat": 64000,
    "deepseek-reasoner": 64000,

    # --- Open Source / Llama ---
    "llama-3.1-405b-instruct": 128000,
    "llama-3.1-70b-instruct": 128000,

    # --- Fallback ---
    "default": 4096
}

MODEL_MAX_OUTPUT_TOKENS = {
    # Reserve enough context for the workflow's bounded output-length retry.
    LLM_NAME: 32768,
    # --- OpenAI ---
    "gpt-4o": 14000,
    "gpt-4o-2024-08-06": 16000,
    "gpt-4o-mini": 16000,
    "o1-preview": 32768,
    "o1-mini": 65536,

    # --- Google Gemini ---
    "gemini-1.5-pro": 8192,
    "gemini-1.5-flash": 8192,
    "gemini-2.0-flash": 8192,
    "gemini-3.0-pro": 8192,

    # --- Xiaomi MiMo ---
    "mimo-v2.5-pro": 131072,

    # --- Anthropic Claude ---
    "claude-3-5-sonnet-20241022": 8192,
    "claude-3-5-haiku": 8192,
    "claude-3-opus": 4096,

    # --- DeepSeek ---
    "deepseek-chat": 8192,
    "deepseek-reasoner": 32768,

    # --- Open Source / Llama ---
    "llama-3.1-405b-instruct": 8192,
    "llama-3.1-70b-instruct": 8192,

    # --- Fallback ---
    "default": 8192
}
