"""Authentication providers for GitHub API (PAT & GitHub App)."""

import logging
import os
import time
from typing import Optional, Tuple
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import base64
import json

from app.config import Settings, get_settings
from app.core.exceptions import GitHubAuthError, GitHubAPIError

logger = logging.getLogger(__name__)


def _generate_rs256_jwt(app_id: str, private_key_pem: bytes) -> str:
    """Generate RS256 JWT for GitHub App authentication without external PyJWT dependency."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iat": now - 60,  # 60s in the past to account for clock drift
        "exp": now + (10 * 60),  # 10 minute expiration
        "iss": app_id,
    }

    def b64_url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_bytes = b64_url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_bytes = b64_url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_bytes}.{payload_bytes}".encode("ascii")

    private_key = serialization.load_pem_private_key(
        private_key_pem,
        password=None,
        backend=default_backend(),
    )

    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    sig_b64 = b64_url_encode(signature)
    return f"{header_bytes}.{payload_bytes}.{sig_b64}"


class GitHubAuthProvider:
    """Manages authentication token resolution for GitHub API requests."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._installation_token: Optional[str] = None
        self._installation_token_expires_at: float = 0.0

    def _get_private_key_bytes(self) -> Optional[bytes]:
        """Load private key from PEM string or file path."""
        if not self.settings.GITHUB_APP_PRIVATE_KEY:
            return None

        raw = self.settings.GITHUB_APP_PRIVATE_KEY.strip()
        if os.path.exists(raw):
            with open(raw, "rb") as f:
                return f.read()

        # Check if it contains PEM header
        if "BEGIN RSA PRIVATE KEY" in raw or "BEGIN PRIVATE KEY" in raw:
            return raw.encode("utf-8")

        # Might be base64-encoded PEM
        try:
            decoded = base64.b64decode(raw)
            if b"PRIVATE KEY" in decoded:
                return decoded
        except Exception:
            pass

        return raw.encode("utf-8")

    async def get_app_installation_token(self, http_client: httpx.AsyncClient) -> str:
        """Exchange GitHub App JWT for an Installation Access Token."""
        now = time.time()
        # Return cached token if valid for more than 60 seconds
        if self._installation_token and (self._installation_token_expires_at - now > 60):
            return self._installation_token

        app_id = self.settings.GITHUB_APP_ID
        inst_id = self.settings.GITHUB_APP_INSTALLATION_ID
        key_bytes = self._get_private_key_bytes()

        if not app_id or not inst_id or not key_bytes:
            raise GitHubAuthError(
                "GitHub App authentication requested but GITHUB_APP_ID, "
                "GITHUB_APP_INSTALLATION_ID, or GITHUB_APP_PRIVATE_KEY is missing."
            )

        jwt_token = _generate_rs256_jwt(app_id, key_bytes)
        url = f"{self.settings.GITHUB_API_URL}/app/installations/{inst_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            resp = await http_client.post(url, headers=headers)
            if resp.status_code != 201:
                raise GitHubAuthError(
                    f"Failed to obtain installation token: HTTP {resp.status_code} - {resp.text}"
                )
            data = resp.json()
            token = data["token"]
            # Typically expires in 1 hour
            self._installation_token = token
            self._installation_token_expires_at = now + 3500
            return token
        except httpx.RequestError as e:
            raise GitHubAPIError(f"Network error exchanging GitHub App token: {e}")

    async def resolve_token(
        self,
        override_token: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Tuple[str, str]:
        """
        Resolve the effective GitHub token and auth scheme.
        Returns (token, token_type).
        """
        # 1. Header override token (highest precedence)
        if override_token:
            clean = override_token.strip()
            if clean.lower().startswith("bearer ") or clean.lower().startswith("token "):
                clean = clean.split(" ", 1)[1].strip()
            return clean, "override_token"

        # 2. Configured Personal Access Token (PAT)
        if self.settings.GITHUB_TOKEN:
            return self.settings.GITHUB_TOKEN.strip(), "pat"

        # 3. GitHub App Authentication
        if (
            self.settings.GITHUB_APP_ID
            and self.settings.GITHUB_APP_INSTALLATION_ID
            and self.settings.GITHUB_APP_PRIVATE_KEY
        ):
            if http_client is None:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    token = await self.get_app_installation_token(client)
            else:
                token = await self.get_app_installation_token(http_client)
            return token, "github_app"

        raise GitHubAuthError(
            "No GitHub authentication token provided. Please provide a GitHub token via "
            "the GITHUB_TOKEN environment variable, GitHub App credentials, or the 'Authorization' / 'X-GitHub-Token' request header."
        )
