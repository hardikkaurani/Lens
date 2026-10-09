import logging
from urllib.parse import urlencode, urlparse
from typing import Optional
import uuid

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
from app.core.encryption import EncryptionError
from app.db.session import get_db
from app.integrations.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubClientError,
    GitHubRateLimitError,
    GitHubTimeoutError,
    get_github_client,
)
from app.integrations.github.schemas import (
    GitHubConnectionStatus,
    GitHubDisconnectResponse,
    GitHubRepoListResponse,
    GitHubRepoSyncResponse,
    GitHubRepositoryResponse,
    GitHubRepositorySelectRequest,
)
from app.integrations.github.service import (
    OAUTH_COOKIE_NAME,
    OAuthStorageError,
    acquire_sync_lock,
    delete_github_connection,
    discover_and_sync_repositories,
    generate_oauth_state,
    generate_session_binding,
    get_github_connection,
    list_connection_repositories,
    release_sync_lock,
    store_oauth_state,
    update_repository_selection,
    upsert_github_connection,
    validate_and_consume_oauth_state,
)
from app.queue.job import enqueue_github_repo_sync_job

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

    # 1. Generate cryptographic state and independent browser session binding
    state = generate_oauth_state()
    session_binding = generate_session_binding()

    state_meta = {}
    if redirect and _validate_safe_redirect(redirect, settings.FRONTEND_URL):
        state_meta["redirect"] = redirect

    try:
        await store_oauth_state(state, session_binding, state_meta)
    except OAuthStorageError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth storage service temporarily unavailable.",
        )

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

    # 4. Set HttpOnly, SameSite=Lax cookie bound to user browser session
    response = RedirectResponse(
        url=authorize_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    is_secure = settings.APP_ENV != "development"
    response.set_cookie(
        key=OAUTH_COOKIE_NAME,
        value=session_binding,
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
    lens_oauth_session: Optional[str] = Cookie(None, alias=OAUTH_COOKIE_NAME),
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
        resp.delete_cookie(OAUTH_COOKIE_NAME, path="/")
        return resp

    # 2. Validate state existence
    if not state or not state.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state parameter.",
        )

    # 3. Validate browser session binding cookie presence
    if not lens_oauth_session or not lens_oauth_session.strip():
        logger.warning("OAuth browser session binding cookie missing.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth browser session binding.",
        )

    # 4. Validate and atomically consume state with session binding (CSRF & Replay defense)
    try:
        consumed_state = await validate_and_consume_oauth_state(
            state=state,
            expected_session_binding=lens_oauth_session,
        )
    except OAuthStorageError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth storage service temporarily unavailable.",
        )

    if consumed_state is None:
        logger.warning("OAuth state invalid, expired, replayed, or session binding mismatched: %s", state[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is invalid, expired, or not bound to this browser session.",
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
    response.delete_cookie(OAUTH_COOKIE_NAME, path="/")
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


@router.post(
    "/repositories/sync",
    response_model=GitHubRepoSyncResponse,
    summary="Synchronize GitHub repositories",
    description="Discovers and synchronizes accessible repositories from GitHub for the connected account.",
)
async def sync_github_repositories(
    async_sync: bool = Query(False, description="Enqueue in background worker instead of synchronous discovery."),
    db: AsyncSession = Depends(get_db),
    github_client: GitHubClient = Depends(get_github_client),
) -> GitHubRepoSyncResponse:
    """Trigger repository synchronization for the authenticated GitHub user."""
    connection = await get_github_connection(db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active GitHub connection found. Please connect your GitHub account first.",
        )

    # Concurrency guard: acquire lock
    has_lock = await acquire_sync_lock(connection.id)
    if not has_lock:
        return GitHubRepoSyncResponse(
            status="already_syncing",
            message="Repository synchronization is already in progress for this connection.",
        )

    try:
        if async_sync:
            await enqueue_github_repo_sync_job(connection.id)
            return GitHubRepoSyncResponse(
                status="enqueued",
                message="Repository synchronization job enqueued.",
            )

        try:
            result = await discover_and_sync_repositories(
                db=db,
                connection=connection,
                github_client=github_client,
            )
            return GitHubRepoSyncResponse(
                status=result["status"],
                synced_count=result["synced_count"],
                total=result["total"],
                message=f"Successfully synchronized {result['synced_count']} repositories.",
            )
        except GitHubRateLimitError as rate_err:
            headers = {}
            if rate_err.retry_after is not None:
                headers["Retry-After"] = str(rate_err.retry_after)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="GitHub API rate limit exceeded. Please try again later.",
                headers=headers,
            )
        except GitHubAuthError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GitHub access token rejected. Please reconnect your account.",
            )
        except GitHubTimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timeout communicating with GitHub API while synchronizing repositories.",
            )
        except GitHubClientError as client_err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GitHub API error during synchronization: {client_err.message}",
            )
        except EncryptionError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt stored GitHub access token.",
            )
    finally:
        await release_sync_lock(connection.id)


@router.get(
    "/repositories",
    response_model=GitHubRepoListResponse,
    summary="List discovered GitHub repositories",
    description="Returns normalized repository records for the connected GitHub account.",
)
async def list_github_repositories(
    limit: int = Query(50, ge=1, le=100, description="Page limit."),
    offset: int = Query(0, ge=0, description="Page offset."),
    search: Optional[str] = Query(None, max_length=100, description="Filter by repository name."),
    db: AsyncSession = Depends(get_db),
) -> GitHubRepoListResponse:
    """Retrieve discovered GitHub repositories with pagination and filtering."""
    connection = await get_github_connection(db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active GitHub connection found.",
        )

    items, total = await list_connection_repositories(
        db=db,
        connection_id=connection.id,
        limit=limit,
        offset=offset,
        search=search,
    )

    return GitHubRepoListResponse(
        items=[GitHubRepositoryResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/repositories/{repository_id}/selection",
    response_model=GitHubRepositoryResponse,
    summary="Update repository selection state",
    description="Updates whether a repository is selected for future synchronization or indexing.",
)
async def update_github_repository_selection(
    repository_id: uuid.UUID,
    payload: GitHubRepositorySelectRequest,
    db: AsyncSession = Depends(get_db),
) -> GitHubRepositoryResponse:
    """Toggle repository selection state without triggering content ingestion."""
    connection = await get_github_connection(db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active GitHub connection found.",
        )

    updated_repo = await update_repository_selection(
        db=db,
        connection_id=connection.id,
        repository_id=repository_id,
        is_selected=payload.is_selected,
    )
    if not updated_repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found or does not belong to this connection.",
        )

    return GitHubRepositoryResponse.model_validate(updated_repo)

