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
