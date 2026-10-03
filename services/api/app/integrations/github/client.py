import logging
from typing import Any, Optional

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class GitHubClientError(Exception):
    """Base exception for GitHub API client errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GitHubAuthError(GitHubClientError):
    """Raised when GitHub OAuth exchange or credentials fail."""
    pass


class GitHubApiError(GitHubClientError):
    """Raised when upstream GitHub API returns an error response."""
    pass


class GitHubTimeoutError(GitHubClientError):
    """Raised when request to GitHub times out."""
    pass


class GitHubClient:
    """Backend-only HTTP client interacting directly with GitHub's OAuth and REST API."""

    def __init__(self, settings: Optional[Settings] = None, timeout: float = 10.0):
        self.settings = settings or get_settings()
        self.timeout = timeout

    async def exchange_code_for_token(
        self,
        code: str,
        redirect_uri: Optional[str] = None,
    ) -> dict[str, Any]:
        """Exchange temporary OAuth authorization code for an access token.

        Never logs client secret or returned access token.
        """
        if not self.settings.GITHUB_CLIENT_ID or not self.settings.GITHUB_CLIENT_SECRET:
            raise GitHubAuthError("GitHub OAuth is not configured on this server.")

        payload: dict[str, str] = {
            "client_id": self.settings.GITHUB_CLIENT_ID,
            "client_secret": self.settings.GITHUB_CLIENT_SECRET,
            "code": code,
        }
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri

        headers = {
            "Accept": "application/json",
            "User-Agent": "LENS-Integration-Service/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.settings.GITHUB_OAUTH_TOKEN_URL,
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException:
            logger.error("Timeout occurred while exchanging GitHub OAuth code.")
            raise GitHubTimeoutError("Connection to GitHub timed out during token exchange.") from None
        except httpx.RequestError as exc:
            logger.error("Network error during GitHub OAuth exchange: %s", type(exc).__name__)
            raise GitHubApiError("Network error while connecting to GitHub.") from None

        if response.status_code != 200:
            logger.error("GitHub token endpoint returned HTTP status %s", response.status_code)
            raise GitHubAuthError(
                f"GitHub token exchange returned status {response.status_code}.",
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except Exception:
            logger.error("Failed to parse JSON response from GitHub token endpoint.")
            raise GitHubApiError("Malformed response received from GitHub OAuth service.") from None

        if not isinstance(data, dict):
            raise GitHubApiError("Unexpected response shape from GitHub token endpoint.")

        if "error" in data:
            error_msg = data.get("error_description") or data.get("error") or "OAuth code exchange failed."
            logger.warning("GitHub OAuth returned error code: %s", data.get("error"))
            raise GitHubAuthError(str(error_msg))

        access_token = data.get("access_token")
        if not access_token or not isinstance(access_token, str):
            logger.error("GitHub token response missing valid access_token string.")
            raise GitHubAuthError("Access token was not provided by GitHub.")

        return {
            "access_token": access_token,
            "token_type": str(data.get("token_type") or "bearer"),
            "scope": str(data.get("scope") or ""),
        }

    async def get_authenticated_user(self, access_token: str) -> dict[str, Any]:
        """Fetch the authenticated GitHub user profile using a decrypted access token.

        Never logs the access token or headers.
        """
        if not access_token:
            raise GitHubAuthError("Cannot fetch user profile without access token.")

        url = f"{self.settings.GITHUB_API_BASE_URL.rstrip('/')}/user"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "LENS-Integration-Service/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException:
            logger.error("Timeout occurred while requesting authenticated user from GitHub.")
            raise GitHubTimeoutError("Connection to GitHub timed out while fetching user profile.") from None
        except httpx.RequestError as exc:
            logger.error("Network error fetching GitHub user profile: %s", type(exc).__name__)
            raise GitHubApiError("Network error while connecting to GitHub API.") from None

        if response.status_code == 401 or response.status_code == 403:
            logger.warning("GitHub API rejected authentication with status %s", response.status_code)
            raise GitHubAuthError("GitHub rejected the provided access token.", status_code=response.status_code)

        if response.status_code != 200:
            logger.error("GitHub user endpoint returned status %s", response.status_code)
            raise GitHubApiError(
                f"GitHub API returned error status {response.status_code}.",
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except Exception:
            raise GitHubApiError("Malformed JSON response received from GitHub API.") from None

        if not isinstance(data, dict):
            raise GitHubApiError("Unexpected response shape from GitHub user endpoint.")

        user_id = data.get("id")
        username = data.get("login")

        if user_id is None or not username or not isinstance(username, str):
            raise GitHubApiError("GitHub user response did not contain required id and login fields.")

        # Sanitize username (limit length, remove dangerous control characters)
        sanitized_username = "".join(c for c in username if c.isalnum() or c in "-_.")[:255]

        return {
            "id": str(user_id),
            "login": sanitized_username,
        }


_github_client: Optional[GitHubClient] = None


def get_github_client() -> GitHubClient:
    """Return singleton or configured instance of GitHubClient."""
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client
