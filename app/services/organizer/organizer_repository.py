"""Organizer database repository operations."""

import json
import logging
import uuid
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.models import User, UserRole, Organizer
from app.schemas.organizer import OrganizerProfileCreateUpdate

logger = logging.getLogger(__name__)


class OrganizerRepository:
    """Repository handling Organizer database transactions and user role promotions."""

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        """Fetch user by primary key ID."""
        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
        """Fetch user by email address."""
        stmt = select(User).where(User.email == email.lower().strip())
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def authenticate_or_register_email(
        db: AsyncSession,
        email: str,
        password: str,
        full_name: Optional[str] = None
    ) -> User:
        """Authenticates an existing email user or registers a new account."""
        clean_email = email.lower().strip()
        user = await OrganizerRepository.get_user_by_email(db, clean_email)

        if user:
            if user.hashed_password and not verify_password(password, user.hashed_password):
                raise ValueError("Invalid password for this account.")
            # If user had no password (e.g. created via Google), attach password
            if not user.hashed_password:
                user.hashed_password = hash_password(password)
                await db.commit()
                await db.refresh(user)
            return user

        # Create new user
        new_user = User(
            email=clean_email,
            hashed_password=hash_password(password),
            full_name=full_name or clean_email.split("@")[0],
            role=UserRole.USER
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        logger.info(f"Registered new user via email: {clean_email} (ID: {new_user.id})")
        return new_user

    @staticmethod
    async def authenticate_or_register_google(
        db: AsyncSession,
        google_id: str,
        email: str,
        full_name: Optional[str] = None
    ) -> User:
        """Authenticates or provisions a user via Google OAuth profile."""
        clean_email = email.lower().strip()
        stmt = select(User).where((User.google_id == google_id) | (User.email == clean_email))
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if user:
            if not user.google_id:
                user.google_id = google_id
                await db.commit()
                await db.refresh(user)
            return user

        new_user = User(
            email=clean_email,
            google_id=google_id,
            full_name=full_name or clean_email.split("@")[0],
            role=UserRole.USER
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        logger.info(f"Registered new user via Google OAuth: {clean_email} (ID: {new_user.id})")
        return new_user

    @staticmethod
    async def get_organizer_by_user_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[Organizer]:
        """Fetch organizer profile linked to user_id."""
        stmt = select(Organizer).where(Organizer.user_id == user_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_organizer_by_username(
        db: AsyncSession,
        username: str,
        exclude_user_id: Optional[uuid.UUID] = None
    ) -> Optional[Organizer]:
        """Fetch organizer profile linked to unique username/handle."""
        clean_uname = username.strip().lower()
        stmt = select(Organizer).where(func.lower(Organizer.username) == clean_uname)
        if exclude_user_id:
            stmt = stmt.where(Organizer.user_id != exclude_user_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def create_or_update_organizer(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: OrganizerProfileCreateUpdate
    ) -> Organizer:
        """Creates or updates an organizer profile and promotes user role to ORGANIZER."""
        organizer = await OrganizerRepository.get_organizer_by_user_id(db, user_id)
        user = await OrganizerRepository.get_user_by_id(db, user_id)

        if not user:
            raise ValueError("User profile not found.")

        # Check username uniqueness if provided
        if data.username and data.username.strip():
            clean_username = data.username.strip().lower()
            existing_org = await OrganizerRepository.get_organizer_by_username(db, clean_username, exclude_user_id=user_id)
            if existing_org:
                raise ValueError(f"Username '@{clean_username}' is already taken. Please choose a different handle.")

        # Build payout_bank_details JSON if specific fields are passed
        bank_details_json = data.payout_bank_details
        if any([data.telebirr_phone, data.telebirr_name, data.cbe_account, data.cbe_name]):
            bank_obj = {
                "telebirr_phone": (data.telebirr_phone or "").strip(),
                "telebirr_name": (data.telebirr_name or "").strip(),
                "cbe_account": (data.cbe_account or "").strip(),
                "cbe_name": (data.cbe_name or "").strip(),
            }
            bank_details_json = json.dumps(bank_obj)

        if organizer:
            organizer.org_name = data.org_name
            if data.username is not None:
                organizer.username = data.username.strip().lower() if data.username.strip() else None
            if data.category is not None:
                organizer.category = data.category
            if data.logo_url is not None:
                organizer.logo_url = data.logo_url
            if data.bio is not None:
                organizer.bio = data.bio
            if data.support_phone is not None:
                organizer.support_phone = data.support_phone
            if data.social_links is not None:
                organizer.social_links = data.social_links
            if bank_details_json is not None:
                organizer.payout_bank_details = bank_details_json
        else:
            organizer = Organizer(
                user_id=user_id,
                org_name=data.org_name,
                username=data.username.strip().lower() if (data.username and data.username.strip()) else None,
                category=data.category,
                logo_url=data.logo_url,
                bio=data.bio,
                support_phone=data.support_phone,
                social_links=data.social_links,
                payout_bank_details=bank_details_json,
                is_verified=False,
                subscriber_count=0
            )
            db.add(organizer)

        # Promote user role to ORGANIZER
        if user.role != UserRole.ORGANIZER and user.role != UserRole.ADMIN:
            user.role = UserRole.ORGANIZER

        await db.commit()
        await db.refresh(organizer)
        logger.info(f"Successfully saved Organizer profile for user_id={user_id}: {organizer.org_name} (@{organizer.username})")
        return organizer
