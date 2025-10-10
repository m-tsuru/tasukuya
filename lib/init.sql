-- ユーザーテーブル
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    user_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- ギルドテーブル
CREATE TABLE IF NOT EXISTS guilds (
    guild_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_name TEXT,
    create_user TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (create_user) REFERENCES users (user_id)
);

-- タスクリストテーブル
CREATE TABLE IF NOT EXISTS tasklists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, -- Guild.guild_id は INTEGER のため型を合わせています
    prefix TEXT,
    "default" BOOLEAN,
    FOREIGN KEY (guild_id) REFERENCES guilds (guild_id)
);

-- タスクテーブル
-- task_list_id と task_id による複合主キー
CREATE TABLE IF NOT EXISTS tasks (
    task_list_id INTEGER,
    task_id INTEGER,
    task_name TEXT,
    due_date TIMESTAMP,
    done_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (task_list_id, task_id),
    FOREIGN KEY (task_list_id) REFERENCES tasklists (id)
);

-- タスク担当者テーブル
CREATE TABLE IF NOT EXISTS task_assignees (
    id TEXT PRIMARY KEY AUTOINCREMENT,
    task_list_id INTEGER,
    task_id INTEGER,
    user_id TEXT,
    FOREIGN KEY (task_list_id) REFERENCES tasks (task_list_id),
    FOREIGN KEY (task_id) REFERENCES tasks (task_id),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Webセッションテーブル
CREATE TABLE IF NOT EXISTS web_sessions (
    id TEXT PRIMARY KEY,
    guild_id INTEGER, -- Guild.guild_id は INTEGER のため型を合わせています
    session_key TEXT,
    -- server_default=func.now() + func.interval("1 hour") をSQLiteの関数で表現
    expired_at TIMESTAMP DEFAULT (datetime('now', '+1 hour')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guilds (guild_id)
);

-- users テーブルの updated_at を更新するトリガー
CREATE TRIGGER trigger_users_updated_at
AFTER UPDATE ON users
FOR EACH ROW
BEGIN
    UPDATE users
    SET updated_at = CURRENT_TIMESTAMP
    WHERE user_id = OLD.user_id;
END;

-- guilds テーブルの updated_at を更新するトリガー
CREATE TRIGGER trigger_guilds_updated_at
AFTER UPDATE ON guilds
FOR EACH ROW
BEGIN
    UPDATE guilds
    SET updated_at = CURRENT_TIMESTAMP
    WHERE guild_id = OLD.guild_id;
END;

-- tasks テーブルの updated_at を更新するトリガー
CREATE TRIGGER trigger_tasks_updated_at
AFTER UPDATE ON tasks
FOR EACH ROW
BEGIN
    UPDATE tasks
    SET updated_at = CURRENT_TIMESTAMP
    WHERE task_list_id = OLD.task_list_id AND task_id = OLD.task_id;
END;

-- web_sessions テーブルの updated_at を更新するトリガー
CREATE TRIGGER trigger_web_sessions_updated_at
AFTER UPDATE ON web_sessions
FOR EACH ROW
BEGIN
    UPDATE web_sessions
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = OLD.id;
END;
