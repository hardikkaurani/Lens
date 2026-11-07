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

# Add services/api to sys.path so app imports resolve
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "services" / "api"))

from app.db.models import Capture, GitHubConnection, User
from app.db.session import AsyncSessionLocal

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
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        logger.error("Target user with email '%s' does not exist. Aborting.", email)
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

    async with AsyncSessionLocal() as session:
        if args.inspect:
            await inspect_unowned(session)
        elif args.target_user_email:
            await assign_to_user(session, args.target_user_email)
        elif args.purge_unowned:
            await purge_unowned(session)


if __name__ == "__main__":
    asyncio.run(main())

