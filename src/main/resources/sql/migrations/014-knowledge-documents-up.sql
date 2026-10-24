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
