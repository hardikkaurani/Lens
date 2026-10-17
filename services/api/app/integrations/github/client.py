import asyncio
import logging
import random
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


class GitHubRateLimitError(GitHubClientError):
    """Raised when GitHub API rate limits the request (HTTP 403 / 429)."""

    def __init__(
        self,
        message: str = "GitHub API rate limit exceeded.",
        status_code: int = 429,
        retry_after: Optional[int] = None,
        reset_at: Optional[int] = None,
    ):
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after
        self.reset_at = reset_at


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

    async def list_user_repositories(
        self,
        access_token: str,
        page: int = 1,
        per_page: int = 100,
        affiliation: str = "owner,collaborator,organization_member",
        visibility: str = "all",
        sort: str = "updated",
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        """Fetch a paginated list of repositories accessible to the authenticated user.

        Never logs access tokens or sensitive request headers.
        """
        if not access_token or not access_token.strip():
            raise GitHubAuthError("Cannot fetch repositories without valid access token.")

        # Bound pagination bounds defensibly
        safe_page = max(1, page)
        safe_per_page = min(max(1, per_page), 100)

        url = f"{self.settings.GITHUB_API_BASE_URL.rstrip('/')}/user/repos"
        params = {
            "page": safe_page,
            "per_page": safe_per_page,
            "affiliation": affiliation,
            "visibility": visibility,
            "sort": sort,
            "direction": direction,
        }
        headers = {
            "Authorization": f"Bearer {access_token.strip()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "LENS-Integration-Service/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException:
            logger.error("Timeout occurred while fetching repositories from GitHub (page=%s).", safe_page)
            raise GitHubTimeoutError("Connection to GitHub timed out while fetching repositories.") from None
        except httpx.RequestError as exc:
            logger.error("Network error fetching GitHub repositories: %s", type(exc).__name__)
            raise GitHubApiError("Network error while connecting to GitHub API.") from None

        # Check for rate limiting (HTTP 429 or HTTP 403 with rate limit headers)
        if response.status_code == 429 or response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining")
            is_rate_limited = (
                response.status_code == 429
                or remaining == "0"
                or "rate limit" in response.text.lower()
            )
            if is_rate_limited:
                retry_after_hdr = response.headers.get("Retry-After")
                reset_hdr = response.headers.get("X-RateLimit-Reset")
                retry_after: Optional[int] = None
                reset_at: Optional[int] = None

                if retry_after_hdr and retry_after_hdr.isdigit():
                    retry_after = int(retry_after_hdr)
                if reset_hdr and reset_hdr.isdigit():
                    reset_at = int(reset_hdr)

                logger.warning(
                    "GitHub API rate limit encountered (status=%s, remaining=%s, reset=%s, retry_after=%s)",
                    response.status_code,
                    remaining,
                    reset_at,
                    retry_after,
                )
                raise GitHubRateLimitError(
                    "GitHub API rate limit exceeded.",
                    status_code=response.status_code,
                    retry_after=retry_after,
                    reset_at=reset_at,
                )

        if response.status_code == 401:
            logger.warning("GitHub API rejected access token when listing repositories (status=401)")
            raise GitHubAuthError("GitHub rejected access token when accessing repositories.", status_code=401)

        if response.status_code != 200:
            logger.error("GitHub repos endpoint returned status %s", response.status_code)
            raise GitHubApiError(
                f"GitHub API returned error status {response.status_code}.",
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except Exception:
            raise GitHubApiError("Malformed JSON response received from GitHub repositories API.") from None

        if not isinstance(data, list):
            raise GitHubApiError("Unexpected response shape from GitHub repositories API (expected list).")

        return data

    async def _get_request(
        self,
        url: str,
        access_token: str,
        params: Optional[dict[str, Any]] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> Any:
        """Internal bounded HTTP GET request with retries, backoff, and rate limit awareness."""
        if not access_token or not access_token.strip():
            raise GitHubAuthError("Cannot perform request without valid access token.")

        headers = {
            "Authorization": f"Bearer {access_token.strip()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "LENS-Integration-Service/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params, headers=headers)

                # Rate limiting check (HTTP 429 or 403 with remaining=0 or rate limit message)
                if response.status_code in (429, 403):
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    is_rate_limited = (
                        response.status_code == 429
                        or remaining == "0"
                        or "rate limit" in response.text.lower()
                    )
                    if is_rate_limited:
                        retry_after_hdr = response.headers.get("Retry-After")
                        reset_hdr = response.headers.get("X-RateLimit-Reset")
                        retry_after = int(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
                        reset_at = int(reset_hdr) if reset_hdr and reset_hdr.isdigit() else None
                        logger.warning(
                            "GitHub API rate limit encountered (status=%s, remaining=%s, reset=%s, retry_after=%s)",
                            response.status_code,
                            remaining,
                            reset_at,
                            retry_after,
                        )
                        raise GitHubRateLimitError(
                            "GitHub API rate limit exceeded.",
                            status_code=response.status_code,
                            retry_after=retry_after,
                            reset_at=reset_at,
                        )

                # Authentication check
                if response.status_code == 401:
                    logger.warning("GitHub API rejected access token (status=401)")
                    raise GitHubAuthError("GitHub rejected access token.", status_code=401)

                # Transient server errors (500, 502, 503, 504) -> retry with exponential backoff & jitter
                if response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        "GitHub API returned transient error %s (attempt %d/%d)",
                        response.status_code,
                        attempt + 1,
                        max_retries,
                    )
                    if attempt < max_retries - 1:
                        delay = backoff_base * (2 ** attempt) + random.uniform(0.01, 0.1)
                        await asyncio.sleep(delay)
                        continue
                    raise GitHubApiError(
                        f"GitHub API returned transient server error {response.status_code}.",
                        status_code=response.status_code,
                    )

                if response.status_code != 200:
                    logger.error("GitHub API returned error status %s", response.status_code)
                    raise GitHubApiError(
                        f"GitHub API returned error status {response.status_code}.",
                        status_code=response.status_code,
                    )

                try:
                    data = response.json()
                except Exception:
                    raise GitHubApiError("Malformed JSON response received from GitHub API.") from None

                return data

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("Timeout occurred during GitHub request (attempt %d/%d)", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    delay = backoff_base * (2 ** attempt) + random.uniform(0.01, 0.1)
                    await asyncio.sleep(delay)
                    continue
                raise GitHubTimeoutError("Connection to GitHub timed out.") from None
            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning(
                    "Network error during GitHub request: %s (attempt %d/%d)",
                    type(exc).__name__,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    delay = backoff_base * (2 ** attempt) + random.uniform(0.01, 0.1)
                    await asyncio.sleep(delay)
                    continue
                raise GitHubApiError("Network error while connecting to GitHub API.") from None

        if last_exc:
            raise GitHubApiError(f"Request failed after {max_retries} retries.") from last_exc

    async def list_repository_pull_requests(
        self,
        access_token: str,
        owner: str,
        repo: str,
        state: str = "all",
        sort: str = "updated",
        direction: str = "desc",
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch paginated pull requests for a repository."""
        safe_page = max(1, page)
        safe_per_page = min(max(1, per_page), 100)
        url = f"{self.settings.GITHUB_API_BASE_URL.rstrip('/')}/repos/{owner}/{repo}/pulls"
        params = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": safe_page,
            "per_page": safe_per_page,
        }
        data = await self._get_request(url, access_token=access_token, params=params)
        if not isinstance(data, list):
            raise GitHubApiError("Unexpected response shape from GitHub pull requests API (expected list).")
        return data

    async def list_repository_issues(
        self,
        access_token: str,
        owner: str,
        repo: str,
        state: str = "all",
        sort: str = "updated",
        direction: str = "desc",
        since: Optional[str] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch paginated issues for a repository, excluding pull requests."""
        safe_page = max(1, page)
        safe_per_page = min(max(1, per_page), 100)
        url = f"{self.settings.GITHUB_API_BASE_URL.rstrip('/')}/repos/{owner}/{repo}/issues"
        params: dict[str, Any] = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": safe_page,
            "per_page": safe_per_page,
        }
        if since:
            params["since"] = since
        data = await self._get_request(url, access_token=access_token, params=params)
        if not isinstance(data, list):
            raise GitHubApiError("Unexpected response shape from GitHub issues API (expected list).")
        # Important: Filter out pull requests which GitHub includes in issues response
        return [item for item in data if isinstance(item, dict) and "pull_request" not in item]

    async def list_repository_commits(
        self,
        access_token: str,
        owner: str,
        repo: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch paginated commits for a repository."""
        safe_page = max(1, page)
        safe_per_page = min(max(1, per_page), 100)
        url = f"{self.settings.GITHUB_API_BASE_URL.rstrip('/')}/repos/{owner}/{repo}/commits"
        params: dict[str, Any] = {
            "page": safe_page,
            "per_page": safe_per_page,
        }
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        data = await self._get_request(url, access_token=access_token, params=params)
        if not isinstance(data, list):
            raise GitHubApiError("Unexpected response shape from GitHub commits API (expected list).")
        return data

    async def list_pull_request_reviews(
        self,
        access_token: str,
        owner: str,
        repo: str,
        pull_number: int,
        page: int = 1,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch paginated reviews associated with a pull request."""
        safe_page = max(1, page)
        safe_per_page = min(max(1, per_page), 100)
        url = f"{self.settings.GITHUB_API_BASE_URL.rstrip('/')}/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        params = {
            "page": safe_page,
            "per_page": safe_per_page,
        }
        data = await self._get_request(url, access_token=access_token, params=params)
        if not isinstance(data, list):
            raise GitHubApiError("Unexpected response shape from GitHub PR reviews API (expected list).")
        return data



_github_client: Optional[GitHubClient] = None


def get_github_client() -> GitHubClient:
    """Return singleton or configured instance of GitHubClient."""
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client
