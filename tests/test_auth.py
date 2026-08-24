"""Unit tests for authentication resolution."""

import pytest
from app.config import Settings
from app.core.auth import GitHubAuthProvider, _generate_rs256_jwt
from app.core.exceptions import GitHubAuthError
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


@pytest.mark.asyncio
async def test_resolve_header_token():
    settings = Settings(GITHUB_TOKEN="env_token")
    provider = GitHubAuthProvider(settings=settings)

    # Test Bearer header
    token, scheme = await provider.resolve_token("Bearer user_passed_token_123")
    assert token == "user_passed_token_123"
    assert scheme == "override_token"

    # Test raw token header
    token2, _ = await provider.resolve_token("raw_token_xyz")
    assert token2 == "raw_token_xyz"


@pytest.mark.asyncio
async def test_resolve_env_pat():
    settings = Settings(GITHUB_TOKEN="ghp_env_token_456")
    provider = GitHubAuthProvider(settings=settings)

    token, scheme = await provider.resolve_token()
    assert token == "ghp_env_token_456"
    assert scheme == "pat"


@pytest.mark.asyncio
async def test_resolve_missing_token_raises_error():
    settings = Settings(GITHUB_TOKEN=None, GITHUB_APP_ID=None)
    provider = GitHubAuthProvider(settings=settings)

    with pytest.raises(GitHubAuthError) as exc_info:
        await provider.resolve_token()

    assert "No GitHub authentication token provided" in str(exc_info.value)


def test_rsa_jwt_generation():
    # Generate a temporary RSA private key for testing
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    jwt_str = _generate_rs256_jwt(app_id="123456", private_key_pem=pem)
    assert jwt_str is not None
    parts = jwt_str.split(".")
    assert len(parts) == 3  # Header, Payload, Signature
