DROP TABLE IF EXISTS `parliament_source_sync_state`;

ALTER TABLE `parliament_source_record`
  DROP COLUMN `content_changed_at`;
