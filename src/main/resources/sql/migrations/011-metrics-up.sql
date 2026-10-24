CREATE TABLE IF NOT EXISTS tracking_usage_event (
  usage_id bigint unsigned NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id varchar(128) NOT NULL,
  event_kind varchar(32) NOT NULL,
  rating boolean DEFAULT NULL,
  occurred_at timestamp(6) NOT NULL,
  KEY idx_usage_user_time (user_id,occurred_at),
  KEY idx_usage_kind_time (event_kind,occurred_at),
  CONSTRAINT chk_usage_kind CHECK(event_kind IN ('follow_saved','activity_opened','relevance')),
  CONSTRAINT chk_usage_rating CHECK((event_kind='relevance' AND rating IS NOT NULL) OR (event_kind<>'relevance' AND rating IS NULL))
);
