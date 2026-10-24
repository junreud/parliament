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
 CONSTRAINT fk_knowledge_entity_batch FOREIGN KEY(batch_id) REFERENCES knowledge_batch(batch_id)
);
