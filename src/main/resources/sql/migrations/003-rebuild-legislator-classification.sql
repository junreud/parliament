DELETE FROM `parliament_legislator_status`;
DELETE FROM `parliament_legislator_term`;

INSERT IGNORE INTO `parliament_legislator_term`
  (`identity_key`, `assembly_term`, `term_label`, `evidence_source_key`, `evidence_record_key`)
SELECT
  identifier.identity_key,
  CASE
    WHEN terms.term_label = '제헌' THEN 1
    ELSE CAST(REGEXP_REPLACE(terms.term_label, '[^0-9]', '') AS UNSIGNED)
  END,
  terms.term_label,
  record.source_key,
  record.record_key
FROM parliament_source_record record
JOIN parliament_person_identifier identifier
  ON identifier.identifier_namespace = 'OPEN_ASSEMBLY_MEMBER'
 AND identifier.external_id = JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.NAAS_CD'))
JOIN JSON_TABLE(
  CONCAT(
    '["',
    REPLACE(
      REPLACE(JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.GTELT_ERACO')), ' ', ''),
      ',',
      '","'
    ),
    '"]'
  ),
  '$[*]' COLUMNS (`term_label` varchar(32) PATH '$')
) terms
WHERE record.source_key = 'allnamember'
  AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.GTELT_ERACO')) IS NOT NULL
  AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.GTELT_ERACO')) <> ''
  AND (
    terms.term_label = '제헌'
    OR REGEXP_REPLACE(terms.term_label, '[^0-9]', '') <> ''
  );

INSERT IGNORE INTO `parliament_legislator_term`
  (`identity_key`, `assembly_term`, `term_label`, `evidence_source_key`, `evidence_record_key`)
SELECT
  identifier.identity_key,
  CAST(REGEXP_REPLACE(terms.term_label, '[^0-9]', '') AS UNSIGNED),
  terms.term_label,
  record.source_key,
  record.record_key
FROM parliament_source_record record
JOIN parliament_person_identifier identifier
  ON identifier.identifier_namespace = 'OPEN_ASSEMBLY_MEMBER'
 AND identifier.external_id = JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.MONA_CD'))
JOIN JSON_TABLE(
  CONCAT(
    '["',
    REPLACE(
      REPLACE(JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.UNITS')), ' ', ''),
      ',',
      '","'
    ),
    '"]'
  ),
  '$[*]' COLUMNS (`term_label` varchar(32) PATH '$')
) terms
WHERE record.source_key = 'nwvrqwxyaytdsfvhu'
  AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.UNITS')) IS NOT NULL
  AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.UNITS')) <> ''
  AND REGEXP_REPLACE(terms.term_label, '[^0-9]', '') <> '';

INSERT INTO `parliament_legislator_status`
  (`identity_key`, `membership_status`, `current_assembly_term`, `latest_assembly_term`,
   `evidence_source_key`, `evidence_record_key`)
SELECT
  person.identity_key,
  'FORMER',
  NULL,
  MAX(term.assembly_term),
  'allnamember',
  NULL
FROM parliament_person person
LEFT JOIN parliament_legislator_term term ON term.identity_key = person.identity_key
WHERE person.person_kind = 'LEGISLATOR'
GROUP BY person.identity_key;

INSERT INTO `parliament_legislator_status`
  (`identity_key`, `membership_status`, `current_assembly_term`, `latest_assembly_term`,
   `evidence_source_key`, `evidence_record_key`)
SELECT
  identifier.identity_key,
  'CURRENT',
  MAX(term.assembly_term),
  MAX(term.assembly_term),
  record.source_key,
  record.record_key
FROM parliament_source_record record
JOIN parliament_person_identifier identifier
  ON identifier.identifier_namespace = 'OPEN_ASSEMBLY_MEMBER'
 AND identifier.external_id = JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.MONA_CD'))
LEFT JOIN parliament_legislator_term term ON term.identity_key = identifier.identity_key
WHERE record.source_key = 'nwvrqwxyaytdsfvhu'
GROUP BY identifier.identity_key, record.source_key, record.record_key
ON DUPLICATE KEY UPDATE
  membership_status = VALUES(membership_status),
  current_assembly_term = VALUES(current_assembly_term),
  latest_assembly_term = VALUES(latest_assembly_term),
  evidence_source_key = VALUES(evidence_source_key),
  evidence_record_key = VALUES(evidence_record_key),
  classified_at = CURRENT_TIMESTAMP(6);
