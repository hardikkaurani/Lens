from datetime import datetime, timezone
import logging
from urllib.parse import urlencode, urlparse
from typing import Any, Optional
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings, get_settings
from app.core.encryption import EncryptionError
from app.db.models import GitHubRepository
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
    GitHubActivityListResponse,
    GitHubActivityResponse,
    GitHubActivitySyncRequest,
    GitHubActivitySyncResponse,
    GitHubConnectionStatus,
    GitHubDisconnectResponse,
    GitHubRepoListResponse,
    GitHubRepoSyncResponse,
    GitHubRepositoryResponse,
    GitHubRepositorySelectRequest,
    check_sufficient_repo_scope,
)
from app.integrations.github.service import (
    GENERIC_ACTIVITY_SYNC_ERROR_MESSAGE,
    GENERIC_SYNC_ERROR_MESSAGE,
    OAUTH_COOKIE_NAME,
    OAuthStorageError,
    acquire_activity_enqueue_lock,
    acquire_activity_sync_lock,
    acquire_enqueue_lock,
    acquire_sync_lock,
    delete_github_connection,
    discover_and_sync_repositories,
    generate_oauth_state,
    generate_session_binding,
    get_github_connection,
    is_activity_sync_locked,
    is_activity_sync_metadata_active,
    is_sync_locked,
    is_sync_metadata_active,
    list_connection_activities,
    list_connection_repositories,
    release_activity_enqueue_lock,
    release_activity_sync_lock,
    release_enqueue_lock,
    release_sync_lock,
    store_oauth_state,
    sync_selected_repositories_activities,
    update_repository_selection,
    upsert_github_connection,
    validate_and_consume_oauth_state,
)
from app.queue.job import (
    enqueue_github_activity_sync_job,
    enqueue_github_repo_sync_job,
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

    sync_info = (connection.token_metadata or {}).get("sync", {})
    last_synced = None
    if sync_info.get("last_synced_at"):
        try:
            last_synced = datetime.fromisoformat(sync_info["last_synced_at"])
        except Exception:
            pass

    has_required_scope = check_sufficient_repo_scope(connection.scope)
    missing_scope_reason = None
    if not has_required_scope:
        missing_scope_reason = (
            "Your GitHub connection is missing repository permissions (repo or public_repo scope). "
            "Please reconnect your GitHub account to grant repository access."
        )

    return GitHubConnectionStatus(
        connected=True,
        github_username=connection.github_username,
        github_user_id=connection.github_user_id,
        scope=connection.scope,
        connected_at=connection.created_at,
        last_verified_at=connection.last_verified_at,
        sync_status=sync_info.get("status", "idle"),
        last_synced_at=last_synced,
        sync_error=sync_info.get("error"),
        has_required_scope=has_required_scope,
        missing_scope_reason=missing_scope_reason,
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

    # 1. Enforce sufficient repository discovery OAuth scope
    if not check_sufficient_repo_scope(connection.scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GitHub connection lacks required repository permissions (repo or public_repo scope). Please reconnect your GitHub account to grant repository access.",
        )

    # 2. Async background sync path
    if async_sync:
        sync_info = (connection.token_metadata or {}).get("sync", {})
        # Treat persisted syncing metadata as active only if fresh within TTL, or if worker lock held
        if is_sync_metadata_active(sync_info) or await is_sync_locked(connection.id):
            return GitHubRepoSyncResponse(
                status="already_syncing",
                message="Repository synchronization is already in progress for this connection.",
            )

        # Concurrency guard: serialize duplicate enqueue requests
        enqueue_token = await acquire_enqueue_lock(connection.id)
        if not enqueue_token:
            return GitHubRepoSyncResponse(
                status="already_syncing",
                message="Repository synchronization is already in progress for this connection.",
            )

        try:
            # Re-verify under enqueue lock to prevent race condition
            await db.refresh(connection, attribute_names=["token_metadata"])
            sync_info_fresh = (connection.token_metadata or {}).get("sync", {})
            if is_sync_metadata_active(sync_info_fresh) or await is_sync_locked(connection.id):
                return GitHubRepoSyncResponse(
                    status="already_syncing",
                    message="Repository synchronization is already in progress for this connection.",
                )

            # Persist syncing state BEFORE enqueueing the background job
            now = datetime.now(timezone.utc)
            sync_meta = dict(connection.token_metadata or {})
            sync_meta["sync"] = {
                "status": "syncing",
                "started_at": now.isoformat(),
                "error": None,
            }
            connection.token_metadata = sync_meta
            flag_modified(connection, "token_metadata")
            await db.commit()

            # Enqueue background job with failure rollback
            try:
                await enqueue_github_repo_sync_job(connection.id)
            except Exception as enqueue_exc:
                logger.exception(
                    "Failed to enqueue GitHub repository sync job for connection %s: %s",
                    connection.id,
                    enqueue_exc,
                )
                # Handle enqueue failure without leaving a permanently stuck syncing state
                fail_time = datetime.now(timezone.utc)
                fail_meta = dict(connection.token_metadata or {})
                fail_meta["sync"] = {
                    "status": "failed",
                    "failed_at": fail_time.isoformat(),
                    "error": "Failed to enqueue synchronization job.",
                }
                connection.token_metadata = fail_meta
                flag_modified(connection, "token_metadata")
                try:
                    await db.commit()
                except Exception as db_exc:
                    logger.error("Failed to commit failed state after enqueue error: %s", db_exc)
                    await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to queue repository sync. Please retry.",
                )

            return GitHubRepoSyncResponse(
                status="enqueued",
                message="Repository synchronization job enqueued in background worker.",
            )
        finally:
            await release_enqueue_lock(connection.id, enqueue_token)

    # 3. Synchronous sync path
    sync_info = (connection.token_metadata or {}).get("sync", {})
    if is_sync_metadata_active(sync_info):
        return GitHubRepoSyncResponse(
            status="already_syncing",
            message="Repository synchronization is already in progress for this connection.",
        )

    # Concurrency guard: acquire lock with unique ownership token
    lock_token = await acquire_sync_lock(connection.id)
    if not lock_token:
        return GitHubRepoSyncResponse(
            status="already_syncing",
            message="Repository synchronization is already in progress for this connection.",
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
    except Exception as exc:
        logger.exception("Unexpected error during repository sync: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GENERIC_SYNC_ERROR_MESSAGE,
        )
    finally:
        await release_sync_lock(connection.id, lock_token)


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


@router.post(
    "/activities/sync",
    response_model=GitHubActivitySyncResponse,
    summary="Synchronize GitHub repository activities",
    description="Synchronizes pull requests, issues, commits, and reviews for selected repositories.",
)
async def sync_github_activities(
    payload: Optional[GitHubActivitySyncRequest] = None,
    async_sync: bool = Query(False, description="Enqueue in background worker instead of synchronous processing."),
    db: AsyncSession = Depends(get_db),
    github_client: GitHubClient = Depends(get_github_client),
) -> GitHubActivitySyncResponse:
    """Trigger activity synchronization for selected repositories."""
    connection = await get_github_connection(db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active GitHub connection found. Please connect your GitHub account first.",
        )

    # 1. Enforce sufficient repository discovery OAuth scope
    if not check_sufficient_repo_scope(connection.scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GitHub connection lacks required repository permissions (repo or public_repo scope). Please reconnect your GitHub account to grant repository access.",
        )

    repository_ids = payload.repository_ids if payload else None

    # Validate client-supplied repository IDs: ownership and selection state
    if repository_ids:
        stmt = select(GitHubRepository).where(
            GitHubRepository.id.in_(repository_ids),
            GitHubRepository.connection_id == connection.id,
        )
        res = await db.execute(stmt)
        found_repos = {r.id: r for r in res.scalars().all()}
        for r_id in repository_ids:
            if r_id not in found_repos:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository {r_id} not found or does not belong to this connection.",
                )
            if not found_repos[r_id].is_selected:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Repository '{found_repos[r_id].full_name}' is not selected for synchronization.",
                )

    # 2. Async background sync path
    if async_sync:
        sync_info = (connection.token_metadata or {}).get("activity_sync", {})
        if is_activity_sync_metadata_active(sync_info) or await is_activity_sync_locked(connection.id):
            return GitHubActivitySyncResponse(
                status="already_syncing",
                message="Activity synchronization is already in progress for this connection.",
            )

        # Concurrency guard: serialize duplicate enqueue requests
        enqueue_token = await acquire_activity_enqueue_lock(connection.id)
        if not enqueue_token:
            return GitHubActivitySyncResponse(
                status="already_syncing",
                message="Activity synchronization is already in progress for this connection.",
            )

        try:
            # Re-verify under enqueue lock
            await db.refresh(connection, attribute_names=["token_metadata"])
            sync_info_fresh = (connection.token_metadata or {}).get("activity_sync", {})
            if is_activity_sync_metadata_active(sync_info_fresh) or await is_activity_sync_locked(connection.id):
                return GitHubActivitySyncResponse(
                    status="already_syncing",
                    message="Activity synchronization is already in progress for this connection.",
                )

            # Persist syncing state before enqueueing
            now = datetime.now(timezone.utc)
            sync_meta = dict(connection.token_metadata or {})
            sync_meta["activity_sync"] = {
                "status": "syncing",
                "started_at": now.isoformat(),
                "error": None,
            }
            connection.token_metadata = sync_meta
            flag_modified(connection, "token_metadata")
            await db.commit()

            try:
                await enqueue_github_activity_sync_job(
                    connection_id=connection.id,
                    repository_ids=repository_ids,
                )
            except Exception as enqueue_exc:
                logger.exception("Failed to enqueue GitHub activity sync job: %s", enqueue_exc)
                fail_time = datetime.now(timezone.utc)
                fail_meta = dict(connection.token_metadata or {})
                fail_meta["activity_sync"] = {
                    "status": "failed",
                    "failed_at": fail_time.isoformat(),
                    "error": "Failed to enqueue activity synchronization job.",
                }
                connection.token_metadata = fail_meta
                flag_modified(connection, "token_metadata")
                try:
                    await db.commit()
                except Exception as db_exc:
                    logger.error("Failed to commit failed state after enqueue error: %s", db_exc)
                    await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to queue activity sync. Please retry.",
                )

            return GitHubActivitySyncResponse(
                status="enqueued",
                message="GitHub activity synchronization job enqueued in background worker.",
            )
        finally:
            await release_activity_enqueue_lock(connection.id, enqueue_token)

    # 3. Synchronous sync path
    sync_info = (connection.token_metadata or {}).get("activity_sync", {})
    if is_activity_sync_metadata_active(sync_info):
        return GitHubActivitySyncResponse(
            status="already_syncing",
            message="Activity synchronization is already in progress for this connection.",
        )

    lock_token = await acquire_activity_sync_lock(connection.id)
    if not lock_token:
        return GitHubActivitySyncResponse(
            status="already_syncing",
            message="Activity synchronization is already in progress for this connection.",
        )

    try:
        result = await sync_selected_repositories_activities(
            db=db,
            connection_id=connection.id,
            repository_ids=repository_ids,
            github_client=github_client,
        )
        return GitHubActivitySyncResponse(
            status=result.get("status", "completed"),
            synced_repositories=result.get("synced_repositories", 0),
            synced_activities=result.get("synced_activities", 0),
            message=result.get("message", "Activity synchronization finished."),
            details=result.get("details"),
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
            detail="Timeout communicating with GitHub API while synchronizing activities.",
        )
    except GitHubClientError as client_err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error during activity synchronization: {client_err.message}",
        )
    except EncryptionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt stored GitHub access token.",
        )
    except Exception as exc:
        logger.exception("Unexpected error during activity sync: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=GENERIC_ACTIVITY_SYNC_ERROR_MESSAGE,
        )
    finally:
        await release_activity_sync_lock(connection.id, lock_token)


@router.get(
    "/activities",
    response_model=GitHubActivityListResponse,
    summary="List ingested GitHub activities",
    description="Returns paginated and filtered activity records for selected repositories.",
)
async def list_github_activities(
    repository_id: Optional[uuid.UUID] = Query(None, description="Filter by repository UUID."),
    activity_type: Optional[str] = Query(None, description="Filter by type: pull_request, issue, commit, or review."),
    limit: int = Query(50, ge=1, le=100, description="Page limit."),
    offset: int = Query(0, ge=0, description="Page offset."),
    db: AsyncSession = Depends(get_db),
) -> GitHubActivityListResponse:
    """Retrieve ingested GitHub activities with pagination and filtering."""
    connection = await get_github_connection(db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active GitHub connection found.",
        )

    # If repository_id specified, verify repository exists and belongs to this connection
    if repository_id is not None:
        stmt = select(GitHubRepository).where(
            GitHubRepository.id == repository_id,
            GitHubRepository.connection_id == connection.id,
        )
        repo_res = await db.execute(stmt)
        if not repo_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found or does not belong to this connection.",
            )

    items, total = await list_connection_activities(
        db=db,
        connection_id=connection.id,
        repository_id=repository_id,
        activity_type=activity_type,
        limit=limit,
        offset=offset,
    )

    return GitHubActivityListResponse(
        items=[GitHubActivityResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/activities/status",
    summary="Get GitHub activity synchronization status",
    description="Returns aggregate activity synchronization status and per-repository breakdown.",
)
async def get_github_activity_status(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve current activity sync state across selected repositories."""
    connection = await get_github_connection(db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active GitHub connection found.",
        )

    stmt = select(GitHubRepository).where(
        GitHubRepository.connection_id == connection.id,
        GitHubRepository.is_selected.is_(True),
    )
    repo_res = await db.execute(stmt)
    selected_repos = list(repo_res.scalars().all())

    connection_sync_meta = (connection.token_metadata or {}).get("activity_sync", {})

    repo_statuses = []
    for r in selected_repos:
        repo_statuses.append({
            "id": str(r.id),
            "full_name": r.full_name,
            "activity_sync_status": r.activity_sync_status,
            "activity_sync_error": r.activity_sync_error,
            "activity_last_synced_at": r.activity_last_synced_at,
            "activity_sync_metadata": r.activity_sync_metadata,
        })

    return {
        "status": connection_sync_meta.get("status", "idle"),
        "last_synced_at": connection_sync_meta.get("last_synced_at"),
        "synced_repositories": connection_sync_meta.get("synced_repositories", 0),
        "synced_activities": connection_sync_meta.get("synced_activities", 0),
        "error": connection_sync_meta.get("error"),
        "repositories": repo_statuses,
    }


