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
  `next_page` int NOT NULL DEFAULT 1,
  `complete` boolean NOT NULL DEFAULT false,
  `last_page` int DEFAULT NULL,
  `last_success_at` timestamp(6) DEFAULT NULL,
  `updated_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`source_key`)
);
