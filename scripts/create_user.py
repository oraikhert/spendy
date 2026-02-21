#!/usr/bin/env python3
"""Create a user manually. Run with: python scripts/create_user.py --email a@b.com --username myuser --password secret123"""
import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session_maker
from app.schemas.user import UserCreate
from app.services import user_service


async def main():
    parser = argparse.ArgumentParser(description="Create a new user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", dest="full_name", default=None)
    args = parser.parse_args()

    user_data = UserCreate(
        email=args.email,
        username=args.username,
        password=args.password,
        full_name=args.full_name,
    )
    async with async_session_maker() as db:
        try:
            user = await user_service.create_user(user_data, db)
            print(f"Created user: {user.username} (id={user.id})")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
