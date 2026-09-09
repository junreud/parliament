DELETE FROM `parliament_ingestion_checkpoint`
WHERE `variant_key` <> 'default';

ALTER TABLE `parliament_ingestion_checkpoint`
  DROP PRIMARY KEY,
  DROP COLUMN `variant_key`,
  ADD PRIMARY KEY (`source_key`);
