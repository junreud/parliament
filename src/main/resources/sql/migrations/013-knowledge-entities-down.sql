-- Destructive development rollback only; production rollback disables knowledge.enabled.
DROP TABLE IF EXISTS knowledge_entity_version;
DROP TABLE IF EXISTS knowledge_batch;
DROP TABLE IF EXISTS knowledge_identifier;
DROP TABLE IF EXISTS knowledge_public_alias;
DROP TABLE IF EXISTS knowledge_identity_binding;
DROP TABLE IF EXISTS knowledge_entity;
