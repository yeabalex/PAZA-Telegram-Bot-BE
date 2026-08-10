#!/usr/bin/env python3
"""Script to delete all users and associated user data from PostgreSQL."""

import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def delete_all_users():
    print("⚠️  Deletes all users and cascaded user records (interests, tickets, bookmarks, etc.)")
    async with AsyncSessionLocal() as session:
        # Check current count
        count_res = await session.execute(text("SELECT COUNT(*) FROM users;"))
        count = count_res.scalar()
        print(f"Current user count: {count}")

        if count == 0:
            print("No users to delete.")
            return

        # Execute DELETE FROM users
        await session.execute(text("DELETE FROM users;"))
        await session.commit()
        print(f"✅ Successfully deleted all {count} users from PostgreSQL!")


if __name__ == "__main__":
    asyncio.run(delete_all_users())
