-- Export immutable evidence and stop dispatchers before applying this destructive rollback.
DROP TABLE `parliament_processing_outbox`;
DROP TABLE `parliament_source_record_version`;
