CREATE TABLE IF NOT EXISTS tracking_event (
  event_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  latest_version varchar(128) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  created_at timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
CREATE TABLE IF NOT EXISTS tracking_event_version (
  event_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  payload_hash char(64) NOT NULL,
  activity json NOT NULL,
  title varchar(500) NOT NULL,
  summary text DEFAULT NULL,
  activity_type varchar(32) NOT NULL,
  bill_id varchar(128) DEFAULT NULL,
  published_at timestamp(6) NOT NULL,
  review_state varchar(16) NOT NULL DEFAULT 'draft',
  reviewed_by varchar(100) DEFAULT NULL,
  reviewed_at timestamp(6) DEFAULT NULL,
  correction_reason varchar(1000) DEFAULT NULL,
  corrected boolean NOT NULL DEFAULT false,
  PRIMARY KEY (event_id, version_id),
  KEY idx_tracking_publication (review_state, reviewed_at, event_id),
  KEY idx_tracking_bill (bill_id),
  FULLTEXT KEY idx_tracking_search (title, summary) WITH PARSER ngram,
  CONSTRAINT fk_tracking_version_event FOREIGN KEY (event_id) REFERENCES tracking_event(event_id),
  CONSTRAINT chk_tracking_review CHECK (review_state IN ('draft','published','rejected'))
);
CREATE TABLE IF NOT EXISTS tracking_event_person (
  event_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  person_id varchar(128) NOT NULL,
  PRIMARY KEY (event_id, version_id, person_id),
  KEY idx_tracking_person (person_id),
  CONSTRAINT fk_tracking_person_version FOREIGN KEY(event_id,version_id) REFERENCES tracking_event_version(event_id,version_id)
);
CREATE TABLE IF NOT EXISTS tracking_event_topic (
  event_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  topic varchar(128) NOT NULL,
  PRIMARY KEY (event_id, version_id, topic),
  KEY idx_tracking_topic (topic),
  CONSTRAINT fk_tracking_topic_version FOREIGN KEY(event_id,version_id) REFERENCES tracking_event_version(event_id,version_id)
);
CREATE TABLE IF NOT EXISTS tracking_user (
  user_id char(36) NOT NULL PRIMARY KEY,
  email varchar(254) NOT NULL,
  frequency varchar(16) NOT NULL DEFAULT 'weekly',
  unsubscribe_hash char(64) NOT NULL,
  unsubscribe_token varchar(43) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email_enabled boolean NOT NULL DEFAULT false,
  verified_at timestamp(6) DEFAULT NULL,
  created_at timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_tracking_email (email),
  UNIQUE KEY uq_tracking_unsubscribe (unsubscribe_hash),
  CONSTRAINT chk_tracking_frequency CHECK (frequency IN ('weekly','daily','off'))
);
CREATE TABLE IF NOT EXISTS tracking_login_token (
  token_hash char(64) NOT NULL PRIMARY KEY,
  user_id char(36) NOT NULL,
  expires_at timestamp(6) NOT NULL,
  consumed_at timestamp(6) DEFAULT NULL,
  CONSTRAINT fk_tracking_login_user FOREIGN KEY (user_id) REFERENCES tracking_user(user_id)
);
CREATE TABLE IF NOT EXISTS tracking_session (
  session_hash char(64) NOT NULL PRIMARY KEY,
  user_id char(36) NOT NULL,
  csrf_token varchar(64) NOT NULL,
  expires_at timestamp(6) NOT NULL,
  CONSTRAINT fk_tracking_session_user FOREIGN KEY (user_id) REFERENCES tracking_user(user_id)
);
CREATE TABLE IF NOT EXISTS tracking_follow (
  user_id char(36) NOT NULL,
  target_kind varchar(16) NOT NULL,
  target_id varchar(128) NOT NULL,
  PRIMARY KEY (user_id, target_kind, target_id),
  CONSTRAINT fk_tracking_follow_user FOREIGN KEY (user_id) REFERENCES tracking_user(user_id),
  CONSTRAINT chk_tracking_follow_kind CHECK (target_kind IN ('person','topic','bill','issue'))
);
CREATE TABLE IF NOT EXISTS tracking_mail_outbox (
  mail_id char(36) NOT NULL PRIMARY KEY,
  user_id char(36) NOT NULL,
  mail_kind varchar(16) NOT NULL,
  dedupe_key char(64) NOT NULL,
  payload json NOT NULL,
  status varchar(16) NOT NULL DEFAULT 'queued',
  created_at timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_tracking_mail_dedupe (dedupe_key),
  KEY idx_tracking_mail_status (status,created_at),
  CONSTRAINT fk_tracking_mail_user FOREIGN KEY (user_id) REFERENCES tracking_user(user_id)
);
CREATE TABLE IF NOT EXISTS tracking_digest_item (
  user_id char(36) NOT NULL,
  event_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  queued_at timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY(user_id,event_id,version_id),
  CONSTRAINT fk_tracking_digest_user FOREIGN KEY(user_id) REFERENCES tracking_user(user_id),
  CONSTRAINT fk_tracking_digest_version FOREIGN KEY(event_id,version_id) REFERENCES tracking_event_version(event_id,version_id)
);

CREATE TABLE IF NOT EXISTS tracking_auth_rate (
  rate_key char(64) NOT NULL,
  hour_bucket bigint NOT NULL,
  attempts int unsigned NOT NULL,
  PRIMARY KEY(rate_key,hour_bucket)
);

CREATE TABLE IF NOT EXISTS tracking_review_budget (
  review_day date NOT NULL PRIMARY KEY,
  review_count int unsigned NOT NULL DEFAULT 0
);
