ALTER TABLE `parliament_source_record`
  ADD COLUMN `content_changed_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
  AFTER `first_seen_at`;

UPDATE `parliament_source_record`
SET `content_changed_at` = `first_seen_at`;

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
