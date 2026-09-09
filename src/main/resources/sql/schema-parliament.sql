CREATE TABLE `parliament_person` (
  `identity_key` varchar(255) NOT NULL,
  `canonical_name` varchar(100) NOT NULL,
  `person_kind` varchar(32) NOT NULL,
  `resolution_status` varchar(32) NOT NULL,
  `first_seen_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `last_seen_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`identity_key`),
  KEY `idx_parliament_person_name` (`canonical_name`)
);

CREATE TABLE `parliament_person_identifier` (
  `identifier_namespace` varchar(64) NOT NULL,
  `external_id` varchar(255) NOT NULL,
  `identity_key` varchar(255) NOT NULL,
  PRIMARY KEY (`identifier_namespace`, `external_id`),
  KEY `idx_parliament_identifier_person` (`identity_key`)
);

CREATE TABLE `parliament_legislator_term` (
  `identity_key` varchar(255) NOT NULL,
  `assembly_term` smallint unsigned NOT NULL,
  `term_label` varchar(32) NOT NULL,
  `evidence_source_key` varchar(100) NOT NULL,
  `evidence_record_key` varchar(255) NOT NULL,
  `observed_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`identity_key`, `assembly_term`),
  KEY `idx_parliament_legislator_term_number` (`assembly_term`)
);

CREATE TABLE `parliament_legislator_status` (
  `identity_key` varchar(255) NOT NULL,
  `membership_status` varchar(16) NOT NULL,
  `current_assembly_term` smallint unsigned DEFAULT NULL,
  `latest_assembly_term` smallint unsigned DEFAULT NULL,
  `evidence_source_key` varchar(100) DEFAULT NULL,
  `evidence_record_key` varchar(255) DEFAULT NULL,
  `classified_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`identity_key`),
  KEY `idx_parliament_legislator_status` (`membership_status`),
  CONSTRAINT `chk_parliament_legislator_status`
    CHECK (`membership_status` IN ('CURRENT', 'FORMER'))
);

CREATE TABLE `parliament_person_position` (
  `position_key` char(40) NOT NULL,
  `identity_key` varchar(255) NOT NULL,
  `position_title` varchar(255) DEFAULT NULL,
  `organization` varchar(255) DEFAULT NULL,
  `source_key` varchar(100) NOT NULL,
  `source_record_key` varchar(255) NOT NULL,
  `observed_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`position_key`),
  KEY `idx_parliament_position_person` (`identity_key`)
);

CREATE TABLE `parliament_social_account` (
  `identity_key` varchar(255) NOT NULL,
  `platform` varchar(32) NOT NULL,
  `url_hash` char(40) NOT NULL,
  `canonical_url` varchar(1024) NOT NULL,
  `handle` varchar(255) DEFAULT NULL,
  `is_primary` boolean NOT NULL DEFAULT true,
  `verification_status` varchar(32) NOT NULL,
  `official_evidence_source_key` varchar(100) DEFAULT NULL,
  `url_verification_status` varchar(32) NOT NULL DEFAULT 'UNCHECKED',
  `url_http_status` smallint unsigned DEFAULT NULL,
  `resolved_url` varchar(1024) DEFAULT NULL,
  `url_verification_error` varchar(100) DEFAULT NULL,
  `last_url_verified_at` timestamp(6) DEFAULT NULL,
  `last_seen_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`identity_key`, `platform`, `url_hash`),
  KEY `idx_parliament_social_url` (`canonical_url`(255))
);

CREATE TABLE `parliament_source_record` (
  `source_key` varchar(100) NOT NULL,
  `record_key` varchar(255) NOT NULL,
  `api_code` varchar(100) NOT NULL,
  `data_go_kr_id` varchar(100) DEFAULT NULL,
  `payload_hash` char(40) NOT NULL,
  `raw_payload` json NOT NULL,
  `first_seen_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `content_changed_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `last_seen_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`source_key`, `record_key`)
);

CREATE TABLE `parliament_record_person` (
  `source_key` varchar(100) NOT NULL,
  `record_key` varchar(255) NOT NULL,
  `identity_key` varchar(255) NOT NULL,
  PRIMARY KEY (`source_key`, `record_key`, `identity_key`),
  KEY `idx_parliament_record_person_identity` (`identity_key`)
);

CREATE TABLE `parliament_ingestion_checkpoint` (
  `source_key` varchar(100) NOT NULL,
  `variant_key` varchar(40) NOT NULL DEFAULT 'default',
  `next_page` int NOT NULL DEFAULT 1,
  `complete` boolean NOT NULL DEFAULT false,
  `last_page` int DEFAULT NULL,
  `last_success_at` timestamp(6) DEFAULT NULL,
  `updated_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`source_key`, `variant_key`)
);

CREATE TABLE `parliament_source_sync_state` (
  `source_key` varchar(100) NOT NULL,
  `status` varchar(16) NOT NULL,
  `last_started_at` timestamp(6) DEFAULT NULL,
  `last_finished_at` timestamp(6) DEFAULT NULL,
  `last_successful_watermark` timestamp(6) DEFAULT NULL,
  `last_error_code` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`source_key`),
  CONSTRAINT `chk_parliament_source_sync_status`
    CHECK (`status` IN ('RUNNING', 'COMPLETE', 'FAILED'))
);

CREATE TABLE `parliament_ingestion_run` (
  `run_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `trigger_type` varchar(16) NOT NULL,
  `scheduled_for` timestamp(6) DEFAULT NULL,
  `started_at` timestamp(6) NOT NULL,
  `finished_at` timestamp(6) DEFAULT NULL,
  `status` varchar(16) NOT NULL,
  `expected_sources` int unsigned NOT NULL DEFAULT 0,
  `succeeded_sources` int unsigned NOT NULL DEFAULT 0,
  `failed_sources` int unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`run_id`),
  KEY `idx_parliament_ingestion_run_schedule` (`scheduled_for`),
  KEY `idx_parliament_ingestion_run_started` (`started_at`),
  CONSTRAINT `chk_parliament_ingestion_run_trigger`
    CHECK (`trigger_type` IN ('MANUAL', 'AUTOMATIC')),
  CONSTRAINT `chk_parliament_ingestion_run_status`
    CHECK (`status` IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED'))
);

CREATE TABLE `parliament_ingestion_source_run` (
  `source_run_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `run_id` bigint unsigned NOT NULL,
  `source_key` varchar(100) NOT NULL,
  `api_code` varchar(100) NOT NULL,
  `source_name` varchar(255) NOT NULL,
  `expectation` varchar(32) NOT NULL,
  `outcome` varchar(40) NOT NULL,
  `started_at` timestamp(6) DEFAULT NULL,
  `finished_at` timestamp(6) DEFAULT NULL,
  `variants` int unsigned NOT NULL DEFAULT 0,
  `scanned` int unsigned NOT NULL DEFAULT 0,
  `changed_rows` int unsigned NOT NULL DEFAULT 0,
  `unchanged_rows` int unsigned NOT NULL DEFAULT 0,
  `removed_rows` int unsigned NOT NULL DEFAULT 0,
  `pages` int unsigned NOT NULL DEFAULT 0,
  `error_code` varchar(100) DEFAULT NULL,
  `message` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`source_run_id`),
  UNIQUE KEY `uq_parliament_ingestion_source_run` (`run_id`, `source_key`),
  KEY `idx_parliament_ingestion_source_outcome` (`outcome`, `finished_at`),
  KEY `idx_parliament_ingestion_source_key` (`source_key`, `finished_at`),
  CONSTRAINT `fk_parliament_ingestion_source_run`
    FOREIGN KEY (`run_id`) REFERENCES `parliament_ingestion_run` (`run_id`) ON DELETE CASCADE
);

CREATE VIEW `parliament_current_legislator` AS
SELECT
  p.identity_key,
  p.canonical_name,
  s.current_assembly_term,
  s.latest_assembly_term,
  s.classified_at
FROM parliament_person p
JOIN parliament_legislator_status s ON s.identity_key = p.identity_key
WHERE s.membership_status = 'CURRENT';

CREATE VIEW `parliament_former_legislator` AS
SELECT
  p.identity_key,
  p.canonical_name,
  s.latest_assembly_term,
  s.classified_at
FROM parliament_person p
JOIN parliament_legislator_status s ON s.identity_key = p.identity_key
WHERE s.membership_status = 'FORMER';
