import re
from . import settings

def redact_text(value: str) -> str:
    secrets = [settings.LLM_API_KEY, settings.TENDERLY_API_KEY, settings.WEB3_PROVIDER]
    for mapping in (settings.JSONRPCS, settings.SCAN_APIKEYS):
        secrets.extend(url for urls in mapping.values() for url in urls)
    for secret in sorted((secret for secret in secrets if secret), key=len, reverse=True):
        value = value.replace(secret, "[配置已隐藏]")
    value = re.sub(r"(?i)(api[-_]?key[=:\s]+)[^\s&\"'<>]+", r"\1[已隐藏]", value)
    return value

def redact(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
