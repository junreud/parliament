resource "aws_s3_bucket" "evidence" { bucket_prefix = "${var.name}-evidence-" }
resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    id     = "database-backups-only"
    status = "Enabled"
    filter { prefix = "backups/" }
    expiration { days = var.backup_days }
    noncurrent_version_expiration { noncurrent_days = var.backup_days }
  }
}
resource "aws_sqs_queue" "dead" {
  name                      = "${var.name}-dead"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "processing" {
  name                       = "${var.name}-processing"
  visibility_timeout_seconds = 300
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dead.arn, maxReceiveCount = 5 })
}
output "instance_id" { value = aws_instance.server.id }
output "alb_dns" { value = aws_lb.web.dns_name }
output "evidence_bucket" { value = aws_s3_bucket.evidence.id }
output "processing_queue_url" { value = aws_sqs_queue.processing.url }
output "ecr_repository_url" { value = aws_ecr_repository.application.repository_url }
