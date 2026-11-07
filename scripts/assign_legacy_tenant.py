"""Operator Migration Script: Safely resolve unowned legacy records.

Strict Security Constraint:
Never silently assign legacy data to an arbitrary or default user.
An operator must explicitly specify an existing user email or choose to purge unowned records.

Usage:
    python scripts/assign_legacy_tenant.py --target-user-email operator@example.com
    python scripts/assign_legacy_tenant.py --purge-unowned
    python scripts/assign_legacy_tenant.py --inspect
"""

import argparse
import asyncio
import logging
import sys
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Add services/api to sys.path so app imports resolve
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "services" / "api"))

from app.db.models import Capture, GitHubConnection, SourceMetadata, User
from app.db.session import AsyncSessionLocal
from app.storage import get_storage_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("legacy-tenant-migration")


async def inspect_unowned(session: AsyncSession) -> tuple[int, int]:
    """Report counts of captures and github connections lacking a user_id."""
    unowned_captures = (
        await session.execute(
            select(func.count(Capture.id)).where(Capture.user_id.is_(None))
        )
    ).scalar() or 0

    unowned_conns = (
        await session.execute(
            select(func.count(GitHubConnection.id)).where(GitHubConnection.user_id.is_(None))
        )
    ).scalar() or 0

    logger.info("Unowned records detected: Captures=%d, GitHubConnections=%d", unowned_captures, unowned_conns)
    return unowned_captures, unowned_conns


async def assign_to_user(session: AsyncSession, email: str) -> None:
    """Assign unowned records to an existing user."""
    cleaned_email = email.strip().lower()
    if not cleaned_email:
        logger.error("Target user email cannot be empty.")
        sys.exit(1)

    stmt = select(User).where(func.lower(User.email) == cleaned_email)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        logger.error("Target user with email '%s' does not exist. Aborting.", email)
        sys.exit(1)

    # Check for potential unique constraint conflicts on github_connections(user_id, provider)
    existing_conn = (
        await session.execute(
            select(GitHubConnection).where(
                GitHubConnection.user_id == user.id,
                GitHubConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()

    unowned_conns_count = (
        await session.execute(
            select(func.count(GitHubConnection.id)).where(GitHubConnection.user_id.is_(None))
        )
    ).scalar() or 0

    if existing_conn and unowned_conns_count > 0:
        logger.error(
            "Conflict detected: Target user '%s' already has an active GitHub connection. "
            "Assigning unowned GitHub connections would violate unique constraints (user_id, provider). "
            "Please resolve or purge unowned GitHub connections first.",
            user.email,
        )
        sys.exit(1)

    logger.info("Assigning unowned records to user %s (id=%s)...", user.email, user.id)

    cap_res = await session.execute(
        update(Capture).where(Capture.user_id.is_(None)).values(user_id=user.id)
    )
    conn_res = await session.execute(
        update(GitHubConnection).where(GitHubConnection.user_id.is_(None)).values(user_id=user.id)
    )

    await session.commit()
    logger.info("Successfully assigned %d captures and %d connections to user %s.", cap_res.rowcount, conn_res.rowcount, user.email)


async def purge_unowned(session: AsyncSession) -> None:
    """Purge unowned records to ensure clean tenant database isolation."""
    logger.warning("Purging all unowned captures and github connections...")

    # Locate unowned captures with storage objects to clean up storage safely
    unowned_captures_stmt = (
        select(Capture)
        .options(selectinload(Capture.source_metadata))
        .where(Capture.user_id.is_(None))
    )
    unowned_caps = (await session.execute(unowned_captures_stmt)).scalars().all()
    try:
        storage = get_storage_client()
        for cap in unowned_caps:
            if cap.source_metadata and isinstance(cap.source_metadata.payload, dict):
                obj_key = cap.source_metadata.payload.get("object_key")
                bucket = cap.source_metadata.payload.get("bucket")
                if obj_key:
                    try:
                        storage.delete_object(obj_key, bucket=bucket)
                    except Exception as s_err:
                        logger.warning("Failed to delete storage object %s during purge: %s", obj_key, s_err)
    except Exception as init_err:
        logger.warning("Storage client unavailable during purge; skipping object deletion: %s", init_err)

    cap_res = await session.execute(
        delete(Capture).where(Capture.user_id.is_(None))
    )
    conn_res = await session.execute(
        delete(GitHubConnection).where(GitHubConnection.user_id.is_(None))
    )

    await session.commit()
    logger.info("Purged %d unowned captures and %d unowned connections.", cap_res.rowcount, conn_res.rowcount)


async def main() -> None:
    parser = argparse.ArgumentParser(description="LENS Legacy Tenant Resolution CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--inspect", action="store_true", help="Inspect and report count of unowned records.")
    group.add_argument("--target-user-email", type=str, help="Assign unowned records to this registered user.")
    group.add_argument("--purge-unowned", action="store_true", help="Purge all unowned records.")

    args = parser.parse_args()

    if args.target_user_email is not None and not args.target_user_email.strip():
        parser.error("--target-user-email must not be empty.")

    async with AsyncSessionLocal() as session:
        if args.inspect:
            await inspect_unowned(session)
        elif args.target_user_email:
            await assign_to_user(session, args.target_user_email)
        elif args.purge_unowned:
            await purge_unowned(session)


if __name__ == "__main__":
    asyncio.run(main())

