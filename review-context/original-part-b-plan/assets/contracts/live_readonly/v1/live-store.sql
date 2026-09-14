PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
PRAGMA trusted_schema=OFF;
PRAGMA busy_timeout=5000;
PRAGMA user_version=1;
CREATE TABLE run_meta (
 run_id TEXT PRIMARY KEY, source_tree_hash TEXT NOT NULL, config_hash TEXT NOT NULL,
 started_utc TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode='LIVE_READ_ONLY'),
 max_matches INTEGER NOT NULL CHECK(max_matches IN (1,3,5)),
 money_enabled INTEGER NOT NULL CHECK(money_enabled=0)
) STRICT;
CREATE TABLE live_events (
 receive_index INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES run_meta(run_id),
 stream_id TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>=0),
 sequence INTEGER NOT NULL CHECK(sequence>=1), observation_id TEXT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('PROVIDER','OPERATOR','CONTROL')),
 payload_type TEXT NOT NULL CHECK(payload_type IN ('ProviderState','MarketBook','BindingChange','HealthChange')),
 payload_canonical BLOB NOT NULL, previous_hash TEXT NOT NULL CHECK(length(previous_hash)=64),
 content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
 observed_at_utc TEXT NOT NULL, received_mono_us INTEGER NOT NULL CHECK(received_mono_us>=0),
 UNIQUE(run_id,stream_id,generation,sequence), UNIQUE(run_id,observation_id)
) STRICT;
CREATE TABLE stream_cursors (
 cursor_id INTEGER PRIMARY KEY, receive_index INTEGER NOT NULL UNIQUE REFERENCES live_events(receive_index),
 run_id TEXT NOT NULL REFERENCES run_meta(run_id), stream_id TEXT NOT NULL,
 generation INTEGER NOT NULL CHECK(generation>=0), sequence INTEGER NOT NULL CHECK(sequence>=1),
 content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
 UNIQUE(run_id,stream_id,generation,sequence)
) STRICT;
CREATE TABLE projection_versions (
 projection_id INTEGER PRIMARY KEY, receive_index INTEGER NOT NULL REFERENCES live_events(receive_index),
 run_id TEXT NOT NULL REFERENCES run_meta(run_id), binding_id TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=1), canonical_view BLOB NOT NULL,
 content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
 UNIQUE(run_id,binding_id,revision)
) STRICT;
CREATE TABLE request_links (
 receive_index INTEGER NOT NULL REFERENCES live_events(receive_index), request_id TEXT NOT NULL,
 batch_observation_id TEXT NOT NULL, PRIMARY KEY(receive_index,request_id)
) STRICT;
CREATE TABLE run_closures (
 run_id TEXT PRIMARY KEY REFERENCES run_meta(run_id), closed_at_utc TEXT NOT NULL,
 reason_code TEXT NOT NULL, last_receive_index INTEGER REFERENCES live_events(receive_index)
) STRICT;
CREATE TRIGGER live_event_contiguity BEFORE INSERT ON live_events BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM run_closures WHERE run_id=NEW.run_id)
 THEN RAISE(ABORT,'RUN_CLOSED') END;
 SELECT CASE WHEN NEW.sequence<>COALESCE((SELECT MAX(sequence) FROM stream_cursors
 WHERE run_id=NEW.run_id AND stream_id=NEW.stream_id AND generation=NEW.generation),0)+1
 THEN RAISE(ABORT,'SEQUENCE_GAP') END;
 SELECT CASE WHEN NEW.previous_hash<>COALESCE((SELECT content_hash FROM stream_cursors
 WHERE run_id=NEW.run_id AND stream_id=NEW.stream_id AND generation=NEW.generation ORDER BY sequence DESC LIMIT 1),
 '0000000000000000000000000000000000000000000000000000000000000000')
 THEN RAISE(ABORT,'CURSOR_MISMATCH') END;
END;
CREATE TRIGGER live_cursor_binding BEFORE INSERT ON stream_cursors BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM live_events WHERE receive_index=NEW.receive_index
 AND run_id=NEW.run_id AND stream_id=NEW.stream_id AND generation=NEW.generation
 AND sequence=NEW.sequence AND content_hash=NEW.content_hash)
 THEN RAISE(ABORT,'CURSOR_WITHOUT_EVENT') END;
END;
CREATE TRIGGER immutable_run_meta_update BEFORE UPDATE ON run_meta BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_run_meta_delete BEFORE DELETE ON run_meta BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_live_events_update BEFORE UPDATE ON live_events BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_live_events_delete BEFORE DELETE ON live_events BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_stream_cursors_update BEFORE UPDATE ON stream_cursors BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_stream_cursors_delete BEFORE DELETE ON stream_cursors BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_projection_versions_update BEFORE UPDATE ON projection_versions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_projection_versions_delete BEFORE DELETE ON projection_versions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_request_links_update BEFORE UPDATE ON request_links BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_request_links_delete BEFORE DELETE ON request_links BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_run_closures_update BEFORE UPDATE ON run_closures BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
CREATE TRIGGER immutable_run_closures_delete BEFORE DELETE ON run_closures BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECORD'); END;
