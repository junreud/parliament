-- Removes only the query index; immutable evidence and history remain intact.
ALTER TABLE knowledge_entity_version
  DROP KEY idx_knowledge_entity_history;
