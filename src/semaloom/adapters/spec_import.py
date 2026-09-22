"""Bounded OpenAPI document download from deployment-approved origins."""

from __future__ import annotations

from typing import Any

import httpx

MAX_SPEC_BYTES = 1_048_576


def _origin(raw: str) -> tuple[str, str, int | None]:
    url = httpx.URL(raw)
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.fragment:
        raise ValueError("SPEC_ORIGIN_NOT_ALLOWED")
    return url.scheme, url.host, url.port


def fetch_spec(
    url: str,
    *,
    allowed_origins: tuple[str, ...],
    headers: dict[str, str],
    params: dict[str, str],
    auth: httpx.BasicAuth | None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Origins are server configuration, never privileges supplied by the caller."""
    try:
        allowed = {_origin(origin) for origin in allowed_origins}
        if _origin(url) not in allowed:
            raise ValueError("SPEC_ORIGIN_NOT_ALLOWED")
        with httpx.Client(
            timeout=10.0, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            with client.stream("GET", url, headers=headers, params=params, auth=auth) as response:
                if 300 <= response.status_code < 400:
                    raise ValueError("SPEC_REDIRECT_NOT_ALLOWED")
                if response.status_code >= 400:
                    raise ValueError("SPEC_FETCH_FAILED")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_SPEC_BYTES:
                        raise ValueError("SPEC_TOO_LARGE")
                    body.extend(chunk)
                buffered = httpx.Response(200, headers=response.headers, content=bytes(body))
                try:
                    return {"spec": buffered.json(), "format": "json"}
                except ValueError:
                    return {"raw": buffered.text, "format": "text"}
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # Do not include URLs, query parameters, credentials or response bodies.
        raise ValueError("SPEC_FETCH_FAILED") from exc
