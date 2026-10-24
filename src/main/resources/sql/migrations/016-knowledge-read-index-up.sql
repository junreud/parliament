-- Secondary lookup for person/organization graph and profile source snapshots.
-- Apply once after 015. No source, identity, review or event data is changed.
ALTER TABLE knowledge_entity_version
  ADD KEY idx_knowledge_entity_history(entity_id,batch_id);
