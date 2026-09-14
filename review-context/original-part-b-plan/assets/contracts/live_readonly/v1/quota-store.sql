PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA user_version=1;
CREATE TABLE quota_reservations (
 attempt_id TEXT PRIMARY KEY, account_slot TEXT NOT NULL CHECK(account_slot='api-football-primary'),
 scope_id TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN('STATUS','COVERAGE','LOOKUP','BUNDLE','EVENTS_FALLBACK')),
 utc_day TEXT NOT NULL, reserved_at_utc TEXT NOT NULL, boot_id TEXT NOT NULL,
 reserved_mono_us INTEGER NOT NULL CHECK(reserved_mono_us>=0)
) STRICT;
CREATE INDEX quota_day ON quota_reservations(account_slot,utc_day);
CREATE INDEX quota_scope ON quota_reservations(scope_id);
CREATE TABLE quota_outcomes (
 attempt_id TEXT PRIMARY KEY REFERENCES quota_reservations(attempt_id),
 result_code TEXT NOT NULL, observed_daily_limit INTEGER,
 observed_daily_remaining INTEGER, observed_minute_limit INTEGER,
 observed_minute_remaining INTEGER, observed_at_utc TEXT NOT NULL,
 CHECK(observed_daily_remaining IS NULL OR observed_daily_remaining>=0),
 CHECK(observed_minute_remaining IS NULL OR observed_minute_remaining>=0)
) STRICT;
CREATE TRIGGER immutable_quota_reservation_update BEFORE UPDATE ON quota_reservations
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ATTEMPT'); END;
CREATE TRIGGER immutable_quota_reservation_delete BEFORE DELETE ON quota_reservations
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ATTEMPT'); END;
CREATE TRIGGER immutable_quota_outcome_update BEFORE UPDATE ON quota_outcomes
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_OUTCOME'); END;
CREATE TRIGGER immutable_quota_outcome_delete BEFORE DELETE ON quota_outcomes
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_OUTCOME'); END;
