PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA user_version=1;
CREATE TABLE intent_consumptions (
 intent_id TEXT PRIMARY KEY,
 intent_hash TEXT NOT NULL UNIQUE CHECK(length(intent_hash)=64),
 run_id TEXT NOT NULL UNIQUE,
 stage TEXT NOT NULL CHECK(stage IN ('PROVIDER_PROBE','OPERATOR_DISCOVERY','LIVE_READ_ONLY')),
 source_tree_hash TEXT NOT NULL CHECK(length(source_tree_hash)=64),
 config_hash TEXT NOT NULL CHECK(length(config_hash)=64),
 consumed_at_utc TEXT NOT NULL,
 confirmation_kind TEXT NOT NULL CHECK(confirmation_kind='LOCAL_TTY_USER_CONFIRMATION'),
 money_authority INTEGER NOT NULL CHECK(money_authority=0)
) STRICT;
CREATE TRIGGER immutable_intent_update BEFORE UPDATE ON intent_consumptions
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_INTENT'); END;
CREATE TRIGGER immutable_intent_delete BEFORE DELETE ON intent_consumptions
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_INTENT'); END;
