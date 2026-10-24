# Worker 검증 기록 — 2026-10-07

이 문서는 worker 담당자의 자기점검이다. 상위 작업의 독립 코드/보안 검수, 실제 MySQL 통합 검증, 배포 승인을 대신하지 않는다. `worker/**`만 변경했고 커밋·AWS 변경·실제 메일·유료 모델 호출은 하지 않았다.

## 1. SPEC 점검

승인된 `docs/plans/2026-10-07-implementation.md` 및 backend 실제 Activity/SQL 계약과 대조했다.

| 항목 | 구현/검증 결과 |
|---|---|
| 기본 수집 읽기 전용 | `collect` 기본 실행은 파일/DB/AWS 쓰기를 하지 않음. `--output`, `--publish`, `--s3`로 구분 |
| 공식 자료 범위 | korea HTML, OPM HTML, 대통령 공식 board AJAX/일정 JSON. 실제 selector/ID/날짜 구조를 읽어 확인. 날짜 누락·JSON drift는 명시적 실패 |
| 식별/원문/날짜 | source ID+raw hash로 버전 고정. 원문 CAS/최초 관측 보존. publication/occurrence 분리. 제목 중복으로 합치지 않음 |
| 이용 조건 | restricted/unknown 자료는 raw 보존 후 blocked. 대통령 KOGL4 원문의 설명·인용을 공개 event로 만들지 않음 |
| Activity 계약 | `announcement/announced`, nullable occurrence, null summary, 정확한 evidence version. 조직 발표를 장관 개인 행동으로 연결하지 않음 |
| Java outbox | 실제 테이블/상태를 그대로 사용. metadata-only SQS, 성공 후 ack, source/version 영속 dedup. 미지원 API는 raw/명시적 상태 보존 후 archival 완료로 ack |
| 선택적 설명 | 고정 official API HTTP+strict JSON schema, 문장별 evidence/excerpt/hash, parser/prompt/model snapshot 및 usage/단가/비용을 불변 초안으로 저장. 자동 승인/공개 없음 |
| 비용/검수 | 유료 HTTP 전 공유 `PARLIAMENT_REVIEW_LEDGER` 예산 예약, 실측 정산, 실패 예약 유지, 추정 초과 시 추가 호출 차단. 서울 하루 3개 review 제한 API와 backend 별도 공개 검수 |
| 메일 | 기본 private EML preview. 명시적 SES 단일 요청, user→mail 잠금, sending 선커밋/현재 설정 재검사, sent terminal, uncertain/stuck sending 자동 재시도 금지 |
| 운영 패키지 | uv.lock, nonroot uid10001 Dockerfile, bounded CLI command와 환경변수 문서화 |

## 2. SECURITY와 코드 품질 점검

이번 자기점검에서 수정한 문제는 다음과 같다.

- injected HTTP client의 redirect 설정이 공식 host/인증 경계를 우회하지 못하도록 매 요청 `follow_redirects=False`를 적용했다.
- 소스마다 output 디렉터리가 달라 월간 비용 한도가 분리되는 문제를 고쳤다. 공유 원장을 필수로 받고 서로 다른 소스가 같은 한도를 적용하는 테스트를 추가했다.
- 실제 비용이 개별 예약액을 넘었지만 월 한도는 남은 경우에도 추가 유료 요청을 막았다. 당시 단가도 초안에 기록했다.
- malformed 공식 JSON과 목록 publication 누락이 숨겨지지 않도록 명시적 구조/날짜 실패를 남겼다.
- 메일의 header/control 문자, 외부 token URL, UUID/path, 잘못된 활동 ID/version을 거절한다. 미리보기와 실제 발송용 MIME을 나눠 sender 변경 충돌을 방지했다.
- 로그인 만료는 user row 잠금을 기다린 뒤 현재 시각으로 다시 평가한다. SDK retry를 끄고 불명확한 전송 결과를 자동 재발송하지 않는다.
- CLI operational DB 오류도 예외 종류만 로그에 남긴다. payload, 수신자, 원문, API/admin 키와 token을 로그로 출력하지 않는다.

추가 확인: 파라미터 바인딩 SQL, 원격 DB TLS 검증, 표준 HTTP TLS 검증, IAM/SSO SDK chain, 명시적 외부 writes, 제한된 HTTP bytes/page/count, private spool 권한, raw와 생성 주장 분리. 소스/테스트에 committed `print()` 또는 실제 credential 패턴이 없다. 모든 Python 파일은 500줄 미만이다.

남은 한계는 명시적으로 보존했다.

- HTTP host/DNS 사전 검사는 연결 IP를 pin하지 않으며 시스템 DNS/신뢰한 proxy의 동작까지 완전한 wall-clock/네트워크 격리를 보장하지 않는다.
- 로컬 불변 파일은 worker가 덮어쓰지 않는다는 의미이며 filesystem WORM/변조 방지 저장소가 아니다. 단일 consumer/summary worker와 운영 잠금 및 영속 볼륨을 전제로 한다.
- LLM 인용 검증은 reference/정확한 excerpt 검증이다. 의미, 이름/숫자, 발표와 실제 시행의 구분은 사람 검수가 필수다. 실제 모델 지원·응답 품질·실청구는 미검증이다.
- HWP/HWPX/PDF 내용 추출, 전체 회의록 발언/개인 표결 mapping은 지원하지 않는다. 일부 소스의 이용 허락이 없으면 자료를 공개하지 않는다.
- SES sender identity/계정 제한, IAM, 실제 전달과 bounce/complaint callback은 미검증이다. SES 수락은 받은편지함 도착이 아니며 uncertain/stuck sending과 private EML retention은 운영자가 수동 관리한다.
- DB-API mail transaction 테스트는 fake connection이며 실제 MySQL 잠금/Java unsubscribe 경쟁은 상위 통합 검증 대상이다. 실제 컨테이너 빌드/AWS 배포도 상위 작업 대상이다.

## 3. 실행한 검증

- uv.lock으로 만든 별도 Python 3.12.11 환경의 console entry point 확인.
- 전체 pytest: **128 passed**; fake HTTP/SES/S3/SQS 및 합성 공식 구조 fixtures. 인터넷/유료 호출/실제 메일 없는 테스트다.
- Black 및 isort 검사. worker의 모든 Python 파일이 500줄 미만이며 committed print/credential 패턴 검사.

반드시 별도로 필요한 실제 검증은 README의 env를 사용한 source 계약 갱신, 로컬 MySQL 경쟁/복원, 운영자 설정 모델의 소수 비공개 품질 평가, SES 수신/해지 확인, AWS/컨테이너 배포 확인이다. 해당 실행 근거 없이 완료로 보고하지 않는다.

## 4. 운영/Java 통합 계약 재점검

- Java `TrackingAuthPolicy.email`에 허용된 ASCII punctuation을 worker가 축소해 메일을 cancelled 처리하던 문제를 수정했다. 동일 local-part 문자 범위/64자 한도/소문자 정규화를 적용하고 문자별 실제 MIME 파싱을 검증했다. Header control 문자는 계속 거절한다.
- 실제 Java `POST /admin/tracking/events`는 `importDraft`만 호출한다. worker의 `--publish --s3` 조합 테스트도 null-summary 구조 초안만 적재하고 blocked 자료는 private raw 보존에만 포함하며 모델/승인 호출을 하지 않는 것을 확인했다.
- 현재 production Compose의 host loopback DB/backend, `/data` 볼륨, uid10001 bootstrap, 공유 `/data/review.sqlite3`는 worker 계약과 맞는다. Digest/설정 변경/해지의 user→mail 잠금 순서는 worker와 맞는다. Login verify의 token→user 순서와 교착을 피하기 위해 worker의 token 검사는 locking read를 추가하지 않는다.
- 새 Python **3.13.5** 환경에 offline `uv sync --locked --no-editable`로 실제 wheel을 설치하고 repo 밖 `/private/tmp`에서 `PYTHONPATH` 없이 console CLI 및 하위 모듈을 import했다. 로컬 명령도 모두 `--no-editable`로 수정했다. AWS extras wheel은 offline cache에 없어서 이 새 환경의 실제 boto3 설치는 미확인이다.
- root 담당자에게 전달한 운영 항목: mail 100건의 SDK timeout 누적과 단일 worker 10분 timeout의 관계, 공유 worker 비용/인덱스/캐시 복원 절차. DB dump와 S3 raw blobs만으로 SQLite 비용 원장/최초 관측 metadata/summary request cache가 복원되지는 않는다. 정부 단일 source 실패로 뒤 source를 건너뛰던 shell 동작은 root 수정 후 계속 수집/실패 exit 집계로 바뀐 것을 확인했다.

## 5. 실제 보도자료 본문/파생 버전 수정

저장된 korea.kr 156784555/156784550/156784549의 HTML을 네트워크 없이 다시 확인했다. `.view_cont`는 `docConversion`의 `iframe#content_press`와 전재 안내문뿐이며 실제 문서 뷰어/HWP/PDF 본문은 수집하지 않았다. 이에 대응하는 구조의 **합성 fixture**로 회귀 테스트를 추가했다.

- `bodyStatus=disclaimer_only/unavailable`은 제목·게시 metadata 사건(summary null)만 만든다. Excerpt는 원래 headline, locator는 `.view_title h1`이며 범위에는 본문/첨부 미확인을 명시한다. 제목을 전체 발표 내용이나 실제 행동의 검증으로 대체하지 않는다.
- summary scope의 blocked queue를 별도로 남긴다. CLI/provider/protocol 모두 실질 본문 부재를 비용 예약/paid HTTP 전에 차단한다. 본문 내용과 안내문이 함께 있는 자료는 안내문 존재만으로 차단하지 않는다.
- 원문 source hash, record key, identity와 최초 관측/공개일은 유지한다. 파서 버전은 `official-html-v2`이다.
- Activity.version은 원문 hash와 분리했다. `v_` + SHA256(canonical `{parserVersion, activity without version}`)를 사용해 같은 원문에서 파서/근거가 수정되어도 새 불변 초안이 생긴다. Evidence.sourceVersion과 raw-index는 원문 hash를 계속 사용한다.
- 같은 raw의 parser/evidence 변경, 동일 입력 재실행, 최초 collectedAt 고정, raw-index count 미증가, 의안 mapper 변경 후 기존 derived snapshot 유지 및 CLI summary eligibility를 테스트했다. 기존 raw 파일이나 최초 metadata를 덮어쓰지 않았다.
- 코드 수정 후 기존 local non-editable wheel이 재사용되어 새 모듈이 설치되지 않는 현상도 실제 isolated import에서 확인했다. `--reinstall-package parliament-worker`로 다시 빌드한 후 소스 경로 없이 3건 저장 HTML을 재파싱해 headline 근거, 요약 차단, 새 파생 version 및 불변 source hash/최초 시각을 확인했다. 일반 pytest src 경로 검증과 설치된 실행 파일 검증은 분리했다.
- 공식 uv 문서에서 `tool.uv.cache-keys`의 file/glob 문법을 확인하고 `pyproject.toml`과 `src/**/*.py`를 지정했다. 기존 설치 환경에서 일반 locked/non-editable/offline sync가 새 wheel을 만드는 것을 확인했고, pyproject 수정 없이 source mtime를 바꾼 뒤 같은 sync가 다시 build/install하는 것도 확인했다. `/private/tmp`에서 PYTHONPATH 없이 실제 console CLI와 installed content/activity 모듈을 검증했다.
- 공개 coverage에서 첨부 처리 코드와 HTML/파싱/metadata 용어를 제거했다. 첨부는 `한글(HWP)`, `한글(HWPX)`, `PDF`와 `내용 미확인`으로 표시하며 운영 metadata의 status는 그대로 유지한다. 본문 확보/전재 안내/본문 부재 3가지 경우와 변경된 설명의 새 파생 version을 회귀 테스트했다. 같은 저장 HTML 3건을 갱신된 non-editable 설치로 `/private/tmp`에서 읽기만 하여 원문/근거/최초 시각은 유지되고 새 version과 요약 차단이 생성되는 것을 확인했다. 파서 로직 자체는 바뀌지 않아 parser version을 올리지 않았으며 공개 payload 변경으로 version이 달라진다.
