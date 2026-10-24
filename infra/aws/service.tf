data "aws_ami" "linux" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
resource "aws_iam_role" "server" {
  name_prefix        = "${var.name}-"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_role_policy" "runtime" {
  role = aws_iam_role.server.id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = var.runtime_parameter_arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::${var.artifact_bucket}/${var.artifact_key}" },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.evidence.arn}/*" },
    { Effect = "Allow", Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.processing.arn },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], Resource = aws_ecr_repository.application.arn }
  ], var.runtime_kms_key_arn == "" ? [] : [{ Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.runtime_kms_key_arn }], var.ses_identity_arn == "" ? [] : [{ Effect = "Allow", Action = ["ses:SendEmail"], Resource = var.ses_identity_arn, Condition = { StringEquals = { "ses:FromAddress" = var.mail_sender } } }]) })
}
resource "aws_iam_instance_profile" "server" { role = aws_iam_role.server.name }
resource "aws_ecr_repository" "application" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_instance" "server" {
  ami                         = data.aws_ami.linux.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.private.id
  vpc_security_group_ids      = [aws_security_group.server.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.server.name
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }
  root_block_device {
    encrypted   = true
    volume_size = 40
    volume_type = "gp3"
  }
  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    parameter = var.runtime_parameter_name,
    artifact  = "s3://${var.artifact_bucket}/${var.artifact_key}",
    sha       = var.artifact_sha256,
    registry  = split("/", aws_ecr_repository.application.repository_url)[0],
    evidence  = aws_s3_bucket.evidence.id,
    queue     = aws_sqs_queue.processing.url
  })
  depends_on = [aws_route_table_association.private, aws_iam_role_policy.runtime, aws_iam_role_policy_attachment.ssm]
  tags       = { Name = var.name }
}
resource "aws_lb" "web" {
  name               = var.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
}
resource "aws_lb_target_group" "web" {
  name_prefix = "gov-"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/about"
    matcher = "200"
  }
}
resource "aws_lb_target_group_attachment" "web" {
  target_group_arn = aws_lb_target_group.web.arn
  target_id        = aws_instance.server.id
  port             = 3000
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.web.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
