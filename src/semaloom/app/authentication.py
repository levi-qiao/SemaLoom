"""Trusted bearer-token authentication shared by every inbound transport."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from semaloom.runtime.auth import RequestActor


class AuthenticationError(ValueError):
    """The presented credential is absent, invalid, or cannot identify an actor."""


class BearerAuthenticator(Protocol):
    @property
    def issuer(self) -> str: ...

    def authenticate(self, token: str) -> RequestActor: ...


@dataclass(frozen=True)
class DemoTokenAuthenticator:
    tokens: dict[str, RequestActor]
    issuer: str = "http://localhost/local-dev"

    def authenticate(self, token: str) -> RequestActor:
        actor = self.tokens.get(token)
        if actor is None:
            raise AuthenticationError("invalid bearer token")
        return actor


@dataclass(frozen=True)
class JwtAuthenticator:
    """Validate production JWTs before translating trusted claims to RequestActor."""

    issuer: str
    audience: str
    algorithms: tuple[str, ...]
    public_key: str | None = None
    jwks_url: str | None = None
    tenant_claim: str = "tenant"
    roles_claim: str = "roles"

    @classmethod
    def from_environment(cls) -> JwtAuthenticator:
        issuer = os.getenv("SEMALOOM_JWT_ISSUER")
        audience = os.getenv("SEMALOOM_JWT_AUDIENCE")
        public_key = os.getenv("SEMALOOM_JWT_PUBLIC_KEY")
        jwks_url = os.getenv("SEMALOOM_JWT_JWKS_URL")
        if not issuer or not audience or not (public_key or jwks_url):
            raise RuntimeError(
                "production identity requires SEMALOOM_JWT_ISSUER, "
                "SEMALOOM_JWT_AUDIENCE, and one of SEMALOOM_JWT_PUBLIC_KEY or "
                "SEMALOOM_JWT_JWKS_URL"
            )
        algorithms = tuple(
            item.strip()
            for item in os.getenv("SEMALOOM_JWT_ALGORITHMS", "RS256").split(",")
            if item.strip()
        )
        if not algorithms or any(item == "none" for item in algorithms):
            raise RuntimeError("SEMALOOM_JWT_ALGORITHMS must contain signed algorithms")
        return cls(
            issuer=issuer,
            audience=audience,
            algorithms=algorithms,
            public_key=public_key,
            jwks_url=jwks_url,
            tenant_claim=os.getenv("SEMALOOM_JWT_TENANT_CLAIM", "tenant"),
            roles_claim=os.getenv("SEMALOOM_JWT_ROLES_CLAIM", "roles"),
        )

    def authenticate(self, token: str) -> RequestActor:
        try:
            key: Any = self.public_key
            if key is None and self.jwks_url is not None:
                key = jwt.PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            tenant = claims.get(self.tenant_claim)
            roles_value = claims.get(self.roles_claim)
            subject = claims.get("sub")
            if not isinstance(tenant, str) or not tenant:
                raise AuthenticationError("JWT tenant claim is missing")
            if not isinstance(subject, str) or not subject:
                raise AuthenticationError("JWT subject claim is missing")
            if isinstance(roles_value, str):
                roles = tuple(item for item in roles_value.split() if item)
            elif isinstance(roles_value, list) and all(
                isinstance(item, str) for item in roles_value
            ):
                roles = tuple(roles_value)
            else:
                raise AuthenticationError("JWT roles claim is missing")
            if not roles:
                raise AuthenticationError("JWT roles claim is empty")
            return RequestActor(tenant=tenant, subject=subject, roles=roles)
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthenticationError("invalid bearer token") from exc


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("bearer token required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError("bearer token required")
    return token
