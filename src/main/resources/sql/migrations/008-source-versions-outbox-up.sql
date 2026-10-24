CREATE TABLE `parliament_source_record_version` (
  `source_key` varchar(100) NOT NULL,
  `record_key` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `payload_hash` char(40) NOT NULL,
  `api_code` varchar(100) NOT NULL,
  `raw_payload` json NOT NULL,
  `observed_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`source_key`, `record_key`, `payload_hash`),
  KEY `idx_source_version_observed` (`observed_at`)
);

CREATE TABLE `parliament_processing_outbox` (
  `outbox_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `source_key` varchar(100) NOT NULL,
  `record_key` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `payload_hash` char(40) NOT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'PENDING',
  `created_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `attempts` int unsigned NOT NULL DEFAULT 0,
  `last_error` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`outbox_id`),
  UNIQUE KEY `uq_processing_version` (`source_key`, `record_key`, `payload_hash`),
  KEY `idx_processing_pending` (`status`, `created_at`),
  CONSTRAINT `chk_processing_outbox_status` CHECK (`status` IN ('PENDING', 'SENT', 'FAILED'))
);
