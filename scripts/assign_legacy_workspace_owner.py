#!/usr/bin/env python3
"""Explicitly assign retained ownerless Legacy Workspace data to an existing user."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import async_session_maker
from app.services.workspace_service import assign_legacy_owner


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()
    async with async_session_maker() as db:
        try:
            await assign_legacy_owner(db, args.workspace_id, args.user_id)
        except ValueError as exc:
            await db.rollback()
            parser.exit(1, f"{exc}\n")
    print("Legacy Workspace owner assigned.")


if __name__ == "__main__":
    asyncio.run(main())
