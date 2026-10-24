-- Preserve exact-case source identifiers. Previously overwritten rows require source re-collection.
ALTER TABLE parliament_source_record MODIFY record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE parliament_record_person MODIFY record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE parliament_source_record_version MODIFY record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE parliament_processing_outbox MODIFY record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE parliament_person_position MODIFY source_record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE parliament_person_identifier MODIFY evidence_record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL;
ALTER TABLE parliament_legislator_term MODIFY evidence_record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;
ALTER TABLE parliament_legislator_status MODIFY evidence_record_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL;
