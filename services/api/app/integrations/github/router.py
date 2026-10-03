import logging
from urllib.parse import urlencode, urlparse
from typing import Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubClientError,
    GitHubTimeoutError,
    get_github_client,
)
from app.integrations.github.schemas import (
    GitHubConnectionStatus,
    GitHubDisconnectResponse,
)
from app.integrations.github.service import (
    delete_github_connection,
    generate_oauth_state,
    get_github_connection,
    store_oauth_state,
    upsert_github_connection,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/github", tags=["integrations"])


def _validate_safe_redirect(target_url: str, allowed_base: str) -> bool:
    """Ensure redirect targets only local or configured frontend origins (open redirect defense)."""
    if target_url.startswith("/") and not target_url.startswith("//"):
        return True
    try:
        parsed_target = urlparse(target_url)
        parsed_allowed = urlparse(allowed_base)
        return (
            parsed_target.scheme in ("http", "https")
            and parsed_target.netloc == parsed_allowed.netloc
        )
    except Exception:
        return False


@router.get(
    "/connect",
    summary="Initiate GitHub OAuth connection",
    description="Generates cryptographically random state, binds it to session cookie, and redirects to GitHub authorization URL.",
)
async def github_oauth_connect(
    request: Request,
    redirect: Optional[str] = Query(None, description="Optional safe frontend path to return to after completion."),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Initiate OAuth authorization with GitHub."""
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured on this server.",
        )

    # 1. Generate and persist cryptographic state (bound to Redis TTL)
    state = generate_oauth_state()
    state_meta = {}
    if redirect and _validate_safe_redirect(redirect, settings.FRONTEND_URL):
        state_meta["redirect"] = redirect

    await store_oauth_state(state, state_meta)

    # 2. Build redirect URI
    redirect_uri = settings.GITHUB_REDIRECT_URI
    if not redirect_uri:
        redirect_uri = str(request.url_for("github_oauth_callback"))

    # 3. Construct GitHub authorization URL
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": settings.GITHUB_OAUTH_SCOPES,
        "state": state,
    }
    authorize_url = f"{settings.GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    # 4. Set HttpOnly, SameSite=Lax cookie bound to user session
    response = RedirectResponse(
        url=authorize_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    is_secure = settings.APP_ENV != "development"
    response.set_cookie(
        key="lens_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )
    return response


@router.get(
    "/callback",
    summary="GitHub OAuth callback handler",
    description="Validates OAuth state, exchanges code for access token, encrypts token at rest, and persists connection.",
)
async def github_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    lens_oauth_state: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    github_client: GitHubClient = Depends(get_github_client),
) -> RedirectResponse:
    """Handle OAuth callback from GitHub."""
    # 1. Handle GitHub OAuth denial/errors
    if error:
        logger.warning("GitHub OAuth returned error: %s (%s)", error, error_description)
        redirect_target = f"{settings.FRONTEND_URL}/settings?github_error=access_denied"
        resp = RedirectResponse(url=redirect_target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        resp.delete_cookie("lens_oauth_state", path="/")
        return resp

    # 2. Validate state existence
    if not state or not state.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state parameter.",
        )

    # 3. Validate state matching with cookie (CSRF defense)
    if not lens_oauth_state or lens_oauth_state != state:
        logger.warning("OAuth state cookie mismatch or missing cookie.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or mismatched OAuth state.",
        )

    # 4. Validate and single-use consume state from store (Replay defense)
    consumed_state = await validate_and_consume_oauth_state(state)
    if consumed_state is None:
        logger.warning("OAuth state invalid, expired, or already replayed: %s", state[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state has expired or has already been used.",
        )

    # 5. Validate authorization code
    if not code or not code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth authorization code.",
        )

    # 6. Exchange authorization code for access token
    redirect_uri = settings.GITHUB_REDIRECT_URI
    if not redirect_uri:
        redirect_uri = str(request.url_for("github_oauth_callback"))

    try:
        token_data = await github_client.exchange_code_for_token(code, redirect_uri=redirect_uri)
    except GitHubTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout communicating with GitHub OAuth service.",
        )
    except GitHubAuthError as auth_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {auth_err.message}",
        )
    except GitHubClientError as client_err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub service error: {client_err.message}",
        )

    access_token = token_data["access_token"]

    # 7. Fetch authenticated GitHub user identity
    try:
        user_info = await github_client.get_authenticated_user(access_token)
    except GitHubTimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout fetching user identity from GitHub.",
        )
    except GitHubAuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub access token rejected when verifying identity.",
        )
    except GitHubClientError as client_err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to verify GitHub user identity: {client_err.message}",
        )

    # 8. Persist verified connection with encrypted access token
    try:
        await upsert_github_connection(
            db=db,
            github_user_id=user_info["id"],
            github_username=user_info["login"],
            access_token=access_token,
            scope=token_data.get("scope"),
            token_type=token_data.get("token_type"),
            token_metadata={"token_type": token_data.get("token_type")},
        )
    except Exception as db_err:
        logger.exception("Database error persisting GitHub connection: %s", db_err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist GitHub connection in database.",
        )

    # 9. Clean up cookie and redirect to settings
    destination = f"{settings.FRONTEND_URL}/settings?github=connected"
    response = RedirectResponse(
        url=destination,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    response.delete_cookie("lens_oauth_state", path="/")
    return response


@router.get(
    "",
    response_model=GitHubConnectionStatus,
    summary="Get GitHub integration connection status",
    description="Returns public connection metadata without sensitive access tokens or credentials.",
)
async def get_github_status(
    db: AsyncSession = Depends(get_db),
) -> GitHubConnectionStatus:
    """Retrieve connection status of GitHub integration."""
    connection = await get_github_connection(db)
    if not connection:
        return GitHubConnectionStatus(connected=False)

    return GitHubConnectionStatus(
        connected=True,
        github_username=connection.github_username,
        github_user_id=connection.github_user_id,
        scope=connection.scope,
        connected_at=connection.created_at,
        last_verified_at=connection.last_verified_at,
    )


@router.delete(
    "",
    response_model=GitHubDisconnectResponse,
    summary="Disconnect GitHub integration",
    description="Removes stored credentials and connection records. Idempotent.",
)
async def disconnect_github(
    db: AsyncSession = Depends(get_db),
) -> GitHubDisconnectResponse:
    """Disconnect and delete the GitHub integration."""
    await delete_github_connection(db)
    return GitHubDisconnectResponse(
        status="disconnected",
        message="GitHub connection disconnected successfully.",
    )
