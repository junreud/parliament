# 서울 리전 소규모 공개 베타 운영

현재는 검증 가능한 배포 코드이며 AWS에 적용하지 않았습니다. public ALB(HTTPS/기존 ACM) → private EC2 한 대 → Docker 웹/API/MySQL 구성입니다. 외부 원천 조회는 NAT, S3는 gateway endpoint를 사용합니다. SSH·공개 DB·하드코딩된 AWS 키는 없습니다. EC2는 SSM/IAM role, 런타임 비밀은 기존 SSM SecureString으로 받습니다.

## 배포 전 준비

1. 서울 리전 견적에 EC2, EBS, ALB 시간/LCU, NAT 시간/처리량, public IPv4, S3, SQS, AI, 발송, 부가세/환율 여유를 합산합니다. [AWS NAT 가격](https://aws.amazon.com/vpc/pricing/)과 [ALB 가격](https://aws.amazon.com/elasticloadbalancing/pricing/)에서 해당 리전 값을 확인합니다. `monthly-cost.csv`는 빈 견적 양식입니다.
2. 월30만원 이하인 견적, 조회+적재 부하, 실제 복원, 출처 계약을 확인하기 전 `deployment_approved=false`를 유지합니다. 예산 알림은 지출 차단 장치가 아닙니다. 모델은 공유 영속 원장에서 호출 전 예약과 초과 차단을 적용합니다.
3. `t4g.medium`은 ARM64/4GB입니다. 네 컨테이너의 메모리 한도와 단일 worker를 실제 서버에서 검증합니다. `t4g.large` 변경도 견적을 다시 확인합니다. 다중 AZ DB·자동 장애조치는 초기 구성에 포함되지 않습니다.
4. 운영 도메인에 대한 서울 ACM 인증서, private 릴리스 S3 bucket, `/parliament/beta/runtime` SecureString을 준비합니다. .env 파일을 Terraform 변수/state에 넣지 않습니다. `TRACKING_PUBLIC_BASE_URL=https://실제도메인`을 고정합니다.
5. 각 이미지를 ARM64로 빌드/검증하고 private ECR에 immutable tag로 올린 다음 digest를 확보합니다. Linux ARM64 Docker Compose 바이너리도 공식 배포의 SHA256과 버전을 고정합니다. 업로드·apply는 별도 운영 작업입니다.

```sh
python3 scripts/build_release.py --backend-image REGISTRY/APP@sha256:실제digest \
  --web-image REGISTRY/APP@sha256:실제digest --worker-image REGISTRY/APP@sha256:실제digest \
  --mysql-image mysql@sha256:실제ARM64digest --compose-binary 검증한LinuxARM64Compose \
  --compose-sha256 실제checksum --output release.tar.gz
cd infra/aws
terraform init
terraform fmt -check
terraform validate
```

`terraform.tfvars.example`의 비밀이 아닌 리소스 식별자·릴리스 SHA256·검증한 비용을 채웁니다. ECR 리포지토리는 Terraform이 생성하므로 처음에는 리포지토리 준비 단계와 런타임 배포 단계를 나눠 진행해야 합니다. 아직 실제 계정·ACM·ECR·SSM·S3가 연결된 plan/apply와 컨테이너 빌드는 검증하지 않았습니다. 기존 회사 SSO/CA 구성을 유지합니다.

## 부팅과 잡

부팅 스크립트는 Docker/Python3.11 설치 → 릴리스 checksum 검증 → SecureString의 private .env 생성 → IAM으로 ECR 로그인 → 고정 이미지 실행 순서입니다. Python worker 데이터는 `.local/worker`에 유지하고 uid10001을 사용합니다. secret .env/메일 spool은 공개 웹에 노출하지 않습니다.

- 백업 타이머는 MySQL(서울03시)와 worker 원장(03시20분)을 매일 private S3 `backups/`로 보냅니다.
- Java 자동 수집은 실제 소스 계약 확인 후 `.env`의 선택된 key·6시간/일간/주간 대조 설정으로 켭니다.
- 정부 발표/SQS 타이머는 확인 후 `systemctl enable --now parliament-worker-government.timer parliament-worker-relay.timer parliament-worker-consume.timer`로 켭니다. 실패한 한 정부 소스가 다른 소스를 막지 않습니다.
- 메일은 SES 송신자 검증·sandbox 범위·반송 대응 확인 후 optional `ses_identity_arn/mail_sender` IAM 권한과 `PARLIAMENT_MAIL_FROM/PARLIAMENT_MAIL_DELIVERY_ENABLED=true`를 설정합니다. digest daily/weekly 타이머와 mail 타이머를 그때 켭니다. 사용자 기본값은 주간입니다.
- 메일은 한번에10건, SDK 재시도 없음입니다. `sending/uncertain`은 자동 재전송하지 않고 SES 태그의 mail ID를 운영자가 대조합니다. 정확히 한 번 배달됐다고 추정하지 않습니다.
- 모든 worker 잡은 같은 flock으로 겹치지 않습니다. timer 실패·SQS DLQ·source FAILED/PARTIAL·백업 업로드 실패를 매일 확인합니다. 알림 수신자/외부 모니터링은 실제 운영 설정 전까지 연결되지 않습니다.

## 복원과 롤백

RPO 최대24시간/RTO24시간은 베타 목표입니다. DB와 worker 둘 다 복원 시험을 통과하고 최근 외부 백업이 있음을 확인해야 합니다. MySQL snapshot은 SQL·manifest를, worker snapshot은 `.tar.gz`와 `.tar.json`을 함께 다운로드합니다.

```sh
python3.11 scripts/database_backup.py verify-restore 선택한.sql.gz --image 고정MySQL이미지
python3.11 scripts/worker_backup.py restore 선택한.tar.gz --target 비어있는새디렉터리
```

DB 도구는 새 네트워크 없는 컨테이너에만 복원하고 모든 테이블 행 수와 CHECK TABLE을 대조합니다. worker 도구는 checksum/SQLite integrity를 검증하고 새로운 디렉터리에만 atomic publish합니다. worker 복원 후 `chown -R 10001:10001`로 운영 사용자에게 인계합니다. 기존 데이터나 .env를 덮어쓰지 않습니다.

실제 장애 복원은 발송/수집 타이머 중단 → 새 DB/worker 복원 → 원문·정정 이력/원장 대조 → 조회 확인 → SES의 최근24시간 상태 대조 → 잡 재개 순서입니다. DB 복구 시 이미 발송한 최근 기록이 사라졌을 가능성이 있어, 대조 전에는 메일 자동 발송을 켜지 않습니다. 애플리케이션 롤백은 이미지 digest를 되돌리고 데이터 볼륨·S3 원문·버전·원장은 유지합니다. SQL down/볼륨 삭제로 배포를 되돌리지 않습니다.

원문 S3 키에는 해시가 포함됩니다. 백업에만30일 lifecycle을 적용하고 raw 원문에는 자동 만료를 적용하지 않습니다. 키 충돌이나 법적 삭제 요청은 별도 운영 절차로 처리합니다. 사용료 실제 합계가 상한을 넘으면 처리량/출시 범위를 줄이고 공개 확대를 보류합니다.
