ALTER TABLE `parliament_social_account`
  ADD COLUMN `official_evidence_source_key` varchar(100) DEFAULT NULL AFTER `verification_status`,
  ADD COLUMN `url_verification_status` varchar(32) NOT NULL DEFAULT 'UNCHECKED' AFTER `official_evidence_source_key`,
  ADD COLUMN `url_http_status` smallint unsigned DEFAULT NULL AFTER `url_verification_status`,
  ADD COLUMN `resolved_url` varchar(1024) DEFAULT NULL AFTER `url_http_status`,
  ADD COLUMN `url_verification_error` varchar(100) DEFAULT NULL AFTER `resolved_url`,
  ADD COLUMN `last_url_verified_at` timestamp(6) DEFAULT NULL AFTER `url_verification_error`;

UPDATE `parliament_social_account` social
JOIN `parliament_record_person` link
  ON link.identity_key = social.identity_key
SET social.verification_status = 'OFFICIAL_DIRECTORY',
    social.official_evidence_source_key = 'negnlnyvatsjwocar'
WHERE link.source_key = 'negnlnyvatsjwocar';

UPDATE `parliament_social_account`
SET verification_status = 'UNVERIFIED'
WHERE verification_status = 'OFFICIAL_DIRECTORY'
  AND official_evidence_source_key IS NULL;
