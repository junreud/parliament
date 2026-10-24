variable "name" {
  type    = string
  default = "parliament-beta"
}
variable "deployment_approved" {
  type        = bool
  default     = false
  description = "Set only after the regional cost estimate, recovery and security checks."
}
variable "estimated_monthly_krw" {
  type        = number
  default     = 0
  description = "Include EC2, ALB, NAT, IPv4, EBS, S3, queues, mail, AI and tax/exchange buffer."
}
variable "certificate_arn" {
  type        = string
  description = "Existing ACM certificate in ap-northeast-2; no HTTP-only public service."
}
variable "runtime_parameter_arn" {
  type        = string
  description = "Existing SSM SecureString containing runtime .env; no secret values in Terraform state."
}
variable "runtime_parameter_name" {
  type = string
  validation {
    condition     = can(regex("^/[A-Za-z0-9_./-]+$", var.runtime_parameter_name))
    error_message = "Use a validated absolute SSM parameter path without shell metacharacters."
  }
}
variable "runtime_kms_key_arn" {
  type        = string
  default     = ""
  description = "Optional customer-managed key used for the runtime parameter."
}
variable "artifact_bucket" {
  type        = string
  description = "Existing private S3 bucket with reviewed deployment artifact."
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.artifact_bucket))
    error_message = "Use a valid private S3 bucket name."
  }
}
variable "artifact_key" {
  type        = string
  description = "Immutable release tar.gz containing production compose file and schema files."
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_./-]+\\.tar\\.gz$", var.artifact_key)) && !strcontains(var.artifact_key, "..")
    error_message = "Use a release tar.gz path without shell metacharacters or parent traversal."
  }
}
variable "artifact_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.artifact_sha256))
    error_message = "Deployment artifact SHA256 required."
  }
}
variable "instance_type" {
  type    = string
  default = "t4g.medium"
  validation {
    condition     = contains(["t4g.medium", "t4g.large"], var.instance_type)
    error_message = "Choose the tested 4GB or 8GB ARM configuration after cost/combined-load validation."
  }
}
variable "backup_days" {
  type    = number
  default = 30
}
variable "ses_identity_arn" {
  type        = string
  default     = ""
  description = "Optional existing verified SES identity; empty disables delivery permission."
}
variable "mail_sender" {
  type        = string
  default     = ""
  description = "Exact verified From address, used to scope optional SES sending."
}
