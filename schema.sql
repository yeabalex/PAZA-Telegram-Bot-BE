-- ================================================================================
-- ADDIS EVENT BOT - COMPLETE POSTGRESQL SCHEMA (BASED ON ERD)
-- ================================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- --------------------------------------------------------------------------------
-- 1. USERS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT UNIQUE NOT NULL,
    full_name VARCHAR(255),
    username VARCHAR(255),
    phone_number VARCHAR(50),
    preferred_language VARCHAR(10) DEFAULT 'en',
    role VARCHAR(20) NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ORGANIZER', 'ADMIN')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 2. ORGANIZERS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_name VARCHAR(255) NOT NULL,
    username VARCHAR(100) UNIQUE,
    category VARCHAR(100),
    logo_url VARCHAR(500),
    bio TEXT,
    support_phone VARCHAR(50),
    social_links JSONB,
    payout_bank_details TEXT,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    subscriber_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 3. INTERESTS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug VARCHAR(100) UNIQUE NOT NULL,
    name_en VARCHAR(255) NOT NULL,
    name_am VARCHAR(255),
    icon_name VARCHAR(100)
);

-- --------------------------------------------------------------------------------
-- 4. USER_INTERESTS TABLE (Junction Table)
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    interest_id UUID NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_interest UNIQUE (user_id, interest_id)
);

-- --------------------------------------------------------------------------------
-- 5. EVENTS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organizer_id UUID REFERENCES organizers(id) ON DELETE SET NULL,
    interest_id UUID REFERENCES interests(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    venue_name VARCHAR(255),
    location_gps VARCHAR(255),
    sub_city VARCHAR(100),
    price_etb NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    image_url VARCHAR(500),
    rsvp_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 6. TRANSACTIONS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tx_ref VARCHAR(255) UNIQUE NOT NULL,
    chapa_pay_tx_id VARCHAR(255),
    amount_etb NUMERIC(10, 2) NOT NULL,
    payment_method VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED', 'EXPIRED')),
    raw_webhook_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 7. TICKETS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transaction_id UUID UNIQUE REFERENCES transactions(id) ON DELETE SET NULL,
    qr_code_hash VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'VALID' CHECK (status IN ('VALID', 'USED', 'CANCELLED')),
    checked_in_at TIMESTAMPTZ,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 8. BOOKMARKS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bookmarks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_bookmark UNIQUE (user_id, event_id)
);

-- --------------------------------------------------------------------------------
-- 9. ORGANIZER_SUBSCRIBERS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizer_subscribers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organizer_id UUID NOT NULL REFERENCES organizers(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_organizer_subscriber UNIQUE (user_id, organizer_id)
);

-- --------------------------------------------------------------------------------
-- 10. HANGOUTS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hangouts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    creator_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    header VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 11. COMMENTS TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    upvote_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------------------
-- 12. COMMENT_UPVOTES TABLE
-- --------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comment_upvotes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    comment_id UUID NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_comment_upvote UNIQUE (user_id, comment_id)
);

-- INDEXES FOR OPTIMAL QUERY PERFORMANCE
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_events_start_time ON events(start_time);
CREATE INDEX IF NOT EXISTS idx_events_organizer_id ON events(organizer_id);
CREATE INDEX IF NOT EXISTS idx_events_interest_id ON events(interest_id);
CREATE INDEX IF NOT EXISTS idx_events_sub_city ON events(sub_city);
CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_event_id ON tickets(event_id);
CREATE INDEX IF NOT EXISTS idx_transactions_tx_ref ON transactions(tx_ref);
CREATE INDEX IF NOT EXISTS idx_comments_event_id ON comments(event_id);
