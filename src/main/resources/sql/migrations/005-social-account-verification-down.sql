ALTER TABLE `parliament_social_account`
  DROP COLUMN `last_url_verified_at`,
  DROP COLUMN `url_verification_error`,
  DROP COLUMN `resolved_url`,
  DROP COLUMN `url_http_status`,
  DROP COLUMN `url_verification_status`,
  DROP COLUMN `official_evidence_source_key`;
