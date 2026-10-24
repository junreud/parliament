-- Additive opt-in beta study. Contact details never enter behavioral or public aggregate rows.
CREATE TABLE IF NOT EXISTS beta_participant (
  participant_id char(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  cohort varchar(16) NOT NULL,
  source varchar(16) NOT NULL,
  consent_version varchar(32) NOT NULL,
  enrolled_at timestamp(6) NOT NULL,
  expires_at timestamp(6) NOT NULL,
  session_hash char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  csrf_token varchar(43) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  UNIQUE KEY uq_beta_session(session_hash),
  KEY idx_beta_expiry(expires_at),
  KEY idx_beta_enrolled(enrolled_at),
  CONSTRAINT chk_beta_cohort CHECK(cohort IN ('friend','external')),
  CONSTRAINT chk_beta_source CHECK(source IN ('instagram','network','community','direct'))
);
CREATE TABLE IF NOT EXISTS beta_contact (
  participant_id char(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  email varchar(254) NOT NULL,
  CONSTRAINT fk_beta_contact_participant FOREIGN KEY(participant_id)
    REFERENCES beta_participant(participant_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS beta_event (
  participant_id char(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  event_kind varchar(32) NOT NULL,
  visit_kind varchar(16) NOT NULL,
  bucket bigint NOT NULL,
  occurred_at timestamp(6) NOT NULL,
  PRIMARY KEY(participant_id,event_kind,visit_kind,bucket),
  KEY idx_beta_event_time(occurred_at),
  CONSTRAINT fk_beta_event_participant FOREIGN KEY(participant_id)
    REFERENCES beta_participant(participant_id) ON DELETE CASCADE,
  CONSTRAINT chk_beta_event CHECK(event_kind IN ('explainer_opened','source_opened','timeline_opened')),
  CONSTRAINT chk_beta_visit CHECK(visit_kind IN ('organic','research'))
);
CREATE TABLE IF NOT EXISTS beta_acquisition (
  day date NOT NULL,
  source varchar(16) NOT NULL,
  visits bigint unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY(day,source),
  CONSTRAINT chk_beta_acquisition_source CHECK(source IN ('instagram','network','community','direct'))
);
