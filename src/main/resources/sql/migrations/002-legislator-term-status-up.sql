CREATE TABLE IF NOT EXISTS `parliament_legislator_term` (
  `identity_key` varchar(255) NOT NULL,
  `assembly_term` smallint unsigned NOT NULL,
  `term_label` varchar(32) NOT NULL,
  `evidence_source_key` varchar(100) NOT NULL,
  `evidence_record_key` varchar(255) NOT NULL,
  `observed_at` timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`identity_key`, `assembly_term`),
  KEY `idx_parliament_legislator_term_number` (`assembly_term`)
);

CREATE TABLE IF NOT EXISTS `parliament_legislator_status` (
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

CREATE OR REPLACE VIEW `parliament_current_legislator` AS
SELECT
  p.identity_key,
  p.canonical_name,
  s.current_assembly_term,
  s.latest_assembly_term,
  s.classified_at
FROM parliament_person p
JOIN parliament_legislator_status s ON s.identity_key = p.identity_key
WHERE s.membership_status = 'CURRENT';

CREATE OR REPLACE VIEW `parliament_former_legislator` AS
SELECT
  p.identity_key,
  p.canonical_name,
  s.latest_assembly_term,
  s.classified_at
FROM parliament_person p
JOIN parliament_legislator_status s ON s.identity_key = p.identity_key
WHERE s.membership_status = 'FORMER';
