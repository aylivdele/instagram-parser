CREATE TABLE users (
    id TEXT PRIMARY KEY,
    telegram_chat_id TEXT UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_active TIMESTAMP
);

CREATE TABLE folders (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#0088cc',
    icon TEXT NOT NULL DEFAULT '📁',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, name)
);

CREATE INDEX idx_folders_user ON folders(user_id, sort_order);

CREATE TABLE instagram_accounts (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_checked TIMESTAMP,
    avg_views_per_hour DOUBLE PRECISION DEFAULT 0,
);

CREATE TABLE user_competitors (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id BIGINT NOT NULL REFERENCES instagram_accounts(id) ON DELETE CASCADE,
    folder_id BIGINT REFERENCES folders(id) ON DELETE SET NULL,
    added_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, account_id)
);

CREATE INDEX idx_user_competitors_user ON user_competitors(user_id);
CREATE INDEX idx_user_competitors_account ON user_competitors(account_id);

CREATE TABLE instagram_posts (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES instagram_accounts(id) ON DELETE CASCADE,
    post_code TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_posts_account ON instagram_posts(account_id, published_at DESC);

CREATE TABLE post_snapshots (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES instagram_posts(id) ON DELETE CASCADE,
    views INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    checked_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_snapshots_post_time 
ON post_snapshots(post_id, checked_at DESC);

CREATE TABLE alerts (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id BIGINT NOT NULL REFERENCES instagram_posts(id) ON DELETE CASCADE,
    detected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    views INTEGER NOT NULL,
    views_per_hour DOUBLE PRECISION NOT NULL,
    avg_views_per_hour DOUBLE PRECISION NOT NULL,
    growth_rate DOUBLE PRECISION NOT NULL,
    sent_to_telegram BOOLEAN DEFAULT FALSE,
    UNIQUE(user_id, post_id)
);

CREATE INDEX idx_alerts_user ON alerts(user_id, detected_at DESC);
