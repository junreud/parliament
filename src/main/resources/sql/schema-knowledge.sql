CREATE TABLE IF NOT EXISTS knowledge_entity (
 entity_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 entity_kind varchar(16) NOT NULL,
 canonical_name varchar(500) NOT NULL,
 published boolean NOT NULL DEFAULT false,
 created_at timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CONSTRAINT chk_knowledge_kind CHECK(entity_kind IN ('person','organization','bill','policy'))
);
CREATE TABLE IF NOT EXISTS knowledge_identity_binding (
 identity_key varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
 entity_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 evidence_batch_id varchar(128) DEFAULT NULL,
 KEY idx_knowledge_binding_entity(entity_id),
 CONSTRAINT fk_knowledge_binding_entity FOREIGN KEY(entity_id) REFERENCES knowledge_entity(entity_id)
);
CREATE TABLE IF NOT EXISTS knowledge_public_alias (
 alias_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 entity_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 CONSTRAINT fk_knowledge_alias_entity FOREIGN KEY(entity_id) REFERENCES knowledge_entity(entity_id)
);
CREATE TABLE IF NOT EXISTS knowledge_identifier (
 namespace varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 external_id varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 entity_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 evidence_batch_id varchar(128) DEFAULT NULL,
 PRIMARY KEY(namespace,external_id),
 CONSTRAINT fk_knowledge_identifier_entity FOREIGN KEY(entity_id) REFERENCES knowledge_entity(entity_id)
);
CREATE TABLE IF NOT EXISTS knowledge_batch (
 batch_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 issue_id varchar(128) NOT NULL,
 payload_hash char(64) NOT NULL,
 payload json NOT NULL,
 review_state varchar(16) NOT NULL DEFAULT 'draft',
 reviewer varchar(100) DEFAULT NULL,
 review_reason varchar(1000) DEFAULT NULL,
 reviewed_at timestamp(6) DEFAULT NULL,
 created_at timestamp(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 KEY idx_knowledge_batch_public(review_state,reviewed_at),
 CONSTRAINT chk_knowledge_batch_review CHECK(review_state IN ('draft','published','rejected'))
);
CREATE TABLE IF NOT EXISTS knowledge_entity_version (
 batch_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 entity_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 payload json NOT NULL,
 PRIMARY KEY(batch_id,entity_id),
 KEY idx_knowledge_entity_history(entity_id,batch_id),
 CONSTRAINT fk_knowledge_entity_batch FOREIGN KEY(batch_id) REFERENCES knowledge_batch(batch_id)
);
CREATE TABLE IF NOT EXISTS knowledge_document_version (
 document_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 version_id char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 content_hash char(64) NOT NULL,
 metadata json NOT NULL,
 first_collected_at timestamp(6) NOT NULL,
 PRIMARY KEY(document_id,version_id)
);
CREATE TABLE IF NOT EXISTS knowledge_document_observation (
 observation_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 document_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 version_id char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 observed_at timestamp(6) NOT NULL,
 transition_id varchar(128) DEFAULT NULL,
 content_hash char(64) NOT NULL,
 KEY idx_knowledge_document_observed(document_id,observed_at),
 CONSTRAINT fk_knowledge_observation_document FOREIGN KEY(document_id,version_id) REFERENCES knowledge_document_version(document_id,version_id)
);
CREATE TABLE IF NOT EXISTS knowledge_extraction (
 document_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 version_id char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 extraction_version varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 content_hash char(64) NOT NULL,
 segments json NOT NULL,
 PRIMARY KEY(document_id,version_id,extraction_version),
 CONSTRAINT fk_knowledge_extraction_document FOREIGN KEY(document_id,version_id) REFERENCES knowledge_document_version(document_id,version_id)
);
CREATE TABLE IF NOT EXISTS knowledge_evidence (
 batch_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 evidence_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 payload json NOT NULL,
 PRIMARY KEY(batch_id,evidence_id),
 CONSTRAINT fk_knowledge_evidence_batch FOREIGN KEY(batch_id) REFERENCES knowledge_batch(batch_id)
);
CREATE TABLE IF NOT EXISTS knowledge_evidence_registry (
 evidence_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 content_hash char(64) NOT NULL,
 payload json NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_relation (
 batch_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 relation_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 subject_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 object_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 relation_type varchar(40) NOT NULL,
 decision varchar(16) NOT NULL,
 payload json NOT NULL,
 PRIMARY KEY(batch_id,relation_id),
 KEY idx_knowledge_relation_subject(subject_id,decision),
 KEY idx_knowledge_relation_object(object_id,decision),
 CONSTRAINT fk_knowledge_relation_batch FOREIGN KEY(batch_id) REFERENCES knowledge_batch(batch_id),
 CONSTRAINT chk_knowledge_relation_decision CHECK(decision IN ('pending','approved','rejected'))
);
CREATE TABLE IF NOT EXISTS knowledge_context (
 event_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 event_version varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 batch_id varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 issue_id varchar(128) NOT NULL,
 content_hash char(64) NOT NULL,
 change_kind varchar(32) NOT NULL,
 sort_at timestamp(6) NOT NULL,
 date_kind varchar(16) NOT NULL,
 payload json NOT NULL,
 PRIMARY KEY(event_id,event_version),
 KEY idx_knowledge_context_issue(issue_id,sort_at,event_id,event_version),
 CONSTRAINT fk_knowledge_context_batch FOREIGN KEY(batch_id) REFERENCES knowledge_batch(batch_id),
 CONSTRAINT fk_knowledge_context_event FOREIGN KEY(event_id,event_version) REFERENCES tracking_event_version(event_id,version_id)
);
