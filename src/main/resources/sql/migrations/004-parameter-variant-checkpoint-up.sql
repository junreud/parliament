ALTER TABLE `parliament_ingestion_checkpoint`
  ADD COLUMN `variant_key` varchar(40) NOT NULL DEFAULT 'default' AFTER `source_key`,
  DROP PRIMARY KEY,
  ADD PRIMARY KEY (`source_key`, `variant_key`);
