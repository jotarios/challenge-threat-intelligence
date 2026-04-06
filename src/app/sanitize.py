import re
from collections.abc import Collection

from fastapi import HTTPException
from starlette.requests import Request

MAX_QUERY_LENGTH = 256

OPENSEARCH_WILDCARD_CHARS = re.compile(r"[*?]")

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def escape_opensearch_wildcard(value: str) -> str:
    return OPENSEARCH_WILDCARD_CHARS.sub(r"\\\g<0>", value)


def clamp_length(value: str, max_length: int = MAX_QUERY_LENGTH) -> str:
    return value[:max_length]


def is_valid_uuid(value: str) -> bool:
    return bool(UUID_PATTERN.match(value))


def sanitize_cache_key_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", value)


def reject_unknown_params(request: Request, allowed: Collection[str]) -> None:
    unknown = set(request.query_params.keys()) - set(allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown query parameters: {', '.join(sorted(unknown))}")
