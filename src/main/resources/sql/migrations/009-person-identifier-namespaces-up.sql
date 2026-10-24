-- Non-destructive schema change only. Legacy OPEN_ASSEMBLY_MEMBER rows remain ambiguous.
-- Rebuild typed mappings from verified raw roster rows in an isolated database; see
-- docs/person-identity-rebuild.md. Never infer a namespace or alias from ID value/name alone.
ALTER TABLE parliament_person_identifier
  MODIFY identifier_namespace varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  MODIFY external_id varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  ADD COLUMN evidence_source_key varchar(100) DEFAULT NULL,
  ADD COLUMN evidence_record_key varchar(255) DEFAULT NULL;
