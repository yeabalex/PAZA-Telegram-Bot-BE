"""User Repository Service — Encapsulates Database operations for Users & Interests."""

import logging
from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Interest, UserInterest, UserRole
from app.schemas.user import UserProfileSchema, InterestSchema

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository handling all database queries for User management and Interest linking."""

    @staticmethod
    async def get_total_users_count(db: AsyncSession) -> int:
        """Count total registered users in PostgreSQL DB."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(User)
        res = await db.execute(stmt)
        return res.scalar() or 0

    @staticmethod
    async def get_by_telegram_id(db: AsyncSession, telegram_id: int) -> Optional[User]:
        """Fetch user by Telegram ID."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_or_create_user(
        db: AsyncSession,
        telegram_id: int,
        full_name: Optional[str] = None,
        username: Optional[str] = None,
        preferred_language: str = "en",
        force_sync: bool = False
    ) -> User:
        """Create or update user upon bot /start or Mini App launch."""
        user = await UserRepository.get_by_telegram_id(db, telegram_id)
        if not user:
            user = User(
                telegram_id=telegram_id,
                full_name=full_name,
                username=username,
                preferred_language=preferred_language,
                role=UserRole.USER
            )
            db.add(user)
            logger.info(f"Registered new user [{telegram_id}]: name='{full_name}', username='{username}'")
        else:
            updated = False
            # Sync full_name if provided and changed
            if full_name is not None and user.full_name != full_name:
                user.full_name = full_name
                updated = True

            # Sync username if changed (handles username added, modified, or removed)
            if force_sync or username is not None:
                if user.username != username:
                    user.username = username
                    updated = True

            if preferred_language and user.preferred_language != preferred_language:
                user.preferred_language = preferred_language
                updated = True

            if updated:
                logger.info(f"Synced updated Telegram profile for user [{telegram_id}]: name='{user.full_name}', username='{user.username}'")

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def update_phone_number(db: AsyncSession, telegram_id: int, phone_number: str) -> Optional[User]:
        """Update user phone number upon contact sharing."""
        user = await UserRepository.get_by_telegram_id(db, telegram_id)
        if not user:
            return None

        user.phone_number = phone_number
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def list_all_interests(db: AsyncSession) -> List[Interest]:
        """List all normalized interests ordered by slug."""
        stmt = select(Interest).order_by(Interest.slug)
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def update_user_interests(db: AsyncSession, telegram_id: int, interest_slugs: List[str]) -> Optional[List[Interest]]:
        """Link selected interest slugs to user in user_interests junction table."""
        user = await UserRepository.get_by_telegram_id(db, telegram_id)
        if not user:
            user = await UserRepository.get_or_create_user(db, telegram_id=telegram_id)

        # Fetch matching interest records
        int_stmt = select(Interest).where(Interest.slug.in_(interest_slugs))
        int_res = await db.execute(int_stmt)
        matching_interests = list(int_res.scalars().all())

        # Clear existing selections
        del_stmt = delete(UserInterest).where(UserInterest.user_id == user.id)
        await db.execute(del_stmt)

        # Insert new selections
        for interest in matching_interests:
            ui = UserInterest(user_id=user.id, interest_id=interest.id)
            db.add(ui)

        await db.commit()
        logger.info(f"Updated interests for user [{telegram_id}]: {[i.slug for i in matching_interests]}")
        return matching_interests

    @staticmethod
    async def get_user_profile(db: AsyncSession, telegram_id: int) -> Optional[UserProfileSchema]:
        """Build UserProfileSchema including selected interests."""
        user = await UserRepository.get_by_telegram_id(db, telegram_id)
        if not user:
            return None

        # Fetch selected interests
        ui_stmt = (
            select(Interest)
            .join(UserInterest, UserInterest.interest_id == Interest.id)
            .where(UserInterest.user_id == user.id)
        )
        ui_res = await db.execute(ui_stmt)
        selected_interests = list(ui_res.scalars().all())

        return UserProfileSchema(
            id=user.id,
            telegram_id=user.telegram_id,
            full_name=user.full_name,
            username=user.username,
            phone_number=user.phone_number,
            preferred_language=user.preferred_language,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            is_registered=True,
            interests=[InterestSchema.model_validate(i) for i in selected_interests]
        )
