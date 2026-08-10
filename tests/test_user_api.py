#!/usr/bin/env python3
"""Integration Test Script for User Registration & Interest Selection API Endpoints."""

import asyncio
import logging
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete
from app.main import app
from app.db.session import AsyncSessionLocal
from app.db.models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestUserAPI")


async def main():
    print("=" * 80)
    print("      TESTING USER REGISTRATION & INTEREST SELECTION ENDPOINTS")
    print("=" * 80)

    test_tg_id = 999888777

    # Cleanup test user from previous runs
    async with AsyncSessionLocal() as session:
        await session.execute(delete(User).where(User.telegram_id == test_tg_id))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test Listing Interests
        res_int = await client.get("/api/v1/interests")
        print(f"\n1. GET /api/v1/interests -> Status {res_int.status_code}")
        interests = res_int.json()
        print(f"   Found {len(interests)} normalized interests: {[i['slug'] for i in interests]}")
        assert res_int.status_code == 200
        assert len(interests) >= 8

        # 2. Test Bot Start Registration (First time — phone_number is None)
        res_start = await client.post(
            "/api/v1/users/bot-start",
            json={
                "telegram_id": test_tg_id,
                "full_name": "Yeabsira TestUser",
                "username": "yeabsira_test",
                "preferred_language": "en"
            }
        )
        print(f"\n2. POST /api/v1/users/bot-start -> Status {res_start.status_code}")
        user_data = res_start.json()
        print(f"   Created User ID: {user_data.get('id')} | is_registered: {user_data.get('is_registered')}")
        assert res_start.status_code == 200
        assert user_data.get("is_registered") is False

        # 3. Test Phone Number Update (Contact Share)
        res_phone = await client.post(
            "/api/v1/users/phone-number",
            json={
                "telegram_id": test_tg_id,
                "phone_number": "+251911223344"
            }
        )
        print(f"\n3. POST /api/v1/users/phone-number -> Status {res_phone.status_code}")
        phone_data = res_phone.json()
        print(f"   Updated Phone: {phone_data.get('phone_number')} | is_registered: {phone_data.get('is_registered')}")
        assert res_phone.status_code == 200
        assert phone_data.get("is_registered") is True

        # 4. Test Interest Selection
        res_sel = await client.post(
            "/api/v1/users/interests",
            json={
                "telegram_id": test_tg_id,
                "interest_slugs": ["music", "nightlife", "food"]
            }
        )
        print(f"\n4. POST /api/v1/users/interests -> Status {res_sel.status_code}")
        print(f"   Selected Slugs Response: {res_sel.json()}")
        assert res_sel.status_code == 200

        # 5. Test Get Current User (/me)
        res_me = await client.get(f"/api/v1/users/me?telegram_id={test_tg_id}")
        print(f"\n5. GET /api/v1/users/me -> Status {res_me.status_code}")
        me_data = res_me.json()
        print(f"   User Profile: {me_data.get('full_name')} ({me_data.get('phone_number')})")
        print(f"   User Interests: {[i['slug'] for i in me_data.get('interests', [])]}")
        assert res_me.status_code == 200
        assert len(me_data.get("interests", [])) == 3

    print("\n" + "=" * 80)
    print(" SUCCESS: ALL MODULAR USER & INTEREST ENDPOINT TESTS PASSED!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
