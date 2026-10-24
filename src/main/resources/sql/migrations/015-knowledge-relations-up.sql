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
