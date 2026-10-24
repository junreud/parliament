# 공식 정부 기록 처리 worker

Python 3.11 이상. 기존 Java 수집기는 유지하고, 공식 정부 발표 HTML/JSON 수집과 원문 버전·근거 처리만 분리합니다. 기본 수집 실행은 원문을 읽고 결과 개수만 로그에 남깁니다. 파일 저장, backend 초안 적재, AWS 전송에는 각각 명시적 옵션이 필요합니다. 메일 발송 및 유료 모델 호출도 명시적으로 켠 경우에만 실행합니다.

## 설치와 검증

```sh
cd worker
uv sync --locked --no-editable --extra dev
uv run --locked --no-editable pytest -q
uv run --locked --no-editable black --check src tests
uv run --locked --no-editable isort --check-only src tests
```

`uv.lock`으로 버전을 고정하고 `--no-editable`로 실제 wheel을 설치합니다. 이 환경의 macOS/Python 3.13에서 숨김 속성이 붙은 editable `.pth`가 무시되는 경우도 wheel 설치로 해결합니다. `PYTHONPATH`에 소스 경로를 추가해 설치 검증을 우회하지 않습니다. AWS 어댑터가 필요할 때만 `uv sync --locked --no-editable --extra dev --extra aws`를 실행합니다. 테스트 HTML/JSON은 `tests/fixtures`에 있는 **합성 자료**이며 실제 정책·공직자의 행동을 주장하지 않습니다. 단위 테스트는 네트워크, AWS 리소스, 유료 모델, 이메일을 사용하지 않습니다.

`tool.uv.cache-keys`에 `pyproject.toml`과 `src/**/*.py`를 지정해 소스 수정 후 일반 sync/run에서도 wheel을 다시 빌드합니다. 설정 문법은 [공식 uv cache 문서](https://docs.astral.sh/uv/concepts/cache/)에서 확인했습니다. 이전 캐시를 사용 중이면 최초 한 번 `uv sync --locked --no-editable --reinstall-package parliament-worker --extra dev`로 갱신할 수 있습니다. AWS extras를 사용 중이면 명령에도 `--extra aws`를 유지합니다. 컨테이너는 COPY src가 바뀐 build layer에서 새 wheel을 설치합니다.

## 실행

```sh
# 읽기 전용: 파일 생성 및 외부 시스템 변경 없음
uv run --locked --no-editable parliament-worker collect --source korea --max-pages 1 --max-records 10

# 원문 버전 및 검수 대기 결과를 명시한 디렉터리에 저장
uv run --locked --no-editable parliament-worker collect --source opm --output /tmp/parliament-worker-run

# 대통령 공식 브리핑/연설문/공개일정의 확인된 커넥터
uv run --locked --no-editable parliament-worker collect --source president-briefings --output /tmp/parliament-president
uv run --locked --no-editable parliament-worker collect --source president-speeches --output /tmp/parliament-speeches
uv run --locked --no-editable parliament-worker collect --source president-schedule --output /tmp/parliament-schedule
```

기본은 최근 90일, 목록 2페이지, 최대 30건이며 실행 한도는 90일/10페이지/100건입니다. 페이지 상한에 도달하면 결과는 `bounded`입니다. 이것은 기간 내 모든 기록 수집이 끝났다는 뜻이 아닙니다. 기사별 실패는 `partial`과 오류 종류로 보고하고 원문·키·본문·비밀번호를 로그에 내보내지 않습니다.

`--output`은 `raw/<source identity>/<SHA-256>.bin`, 최초 관측 메타데이터, SQLite 원문 버전 인덱스와 `report.json`을 만듭니다. 원문 버전은 덮어쓰지 않습니다. 재시도 시 최초 `collectedAt`와 원문 버전의 최초 순서를 유지합니다. 같은 원문을 다른 파서로 처리하는 것은 새 원문 관측이나 raw-index 증가로 세지 않습니다. 동일 제목만으로 기사를 합치지 않습니다.

### backend 초안 적재

신뢰하는 고정 backend 주소를 `PARLIAMENT_BACKEND_URL`로 설정합니다. 로컬 기본값은 `http://127.0.0.1:8080`이며 원격은 HTTPS만 허용합니다. 관리 키는 `TRACKING_ADMIN_KEY` 또는 하위 호환 변수 `PARLIAMENT_INGESTION_ADMIN_KEY`에서만 읽습니다. 키를 명령행이나 코드에 쓰지 않습니다.

```sh
uv run --locked --no-editable parliament-worker collect --source korea --output /tmp/parliament-worker-run --publish
```

`--publish`의 동작은 **POST `/admin/tracking/events`로 초안 적재**입니다. 공개 승인 API를 호출하지 않습니다. `X-Parliament-Ingestion-Key` 헤더를 사용하며 인증 헤더를 다른 주소로 보내는 리디렉션을 거절합니다. 생성된 설명은 이 경로로 적재할 수 없습니다. 공개 승인·정정은 backend 관리자 검수에서 별도로 처리합니다.

wire 형식은 backend `Activity`와 같습니다: `type=announcement`, `stage=announced`, `summary=null`, `occurredAt`은 원문에 명시된 경우에만 설정하며 `publishedAt`/`collectedAt`은 구분합니다. `coverage`는 부처/담당 조직과 기록의 한계를 설명하는 문자열입니다. Evidence의 `sourceVersion`은 원문 SHA-256이고 **Activity.version은 별도의 `v_<derived SHA-256>`**입니다. `{parserVersion, activity}`를 canonical JSON으로 직렬화해 해시하며 activity의 version 자신은 제외합니다. 최초 `collectedAt`를 사용해 동일 입력은 같은 파생 version이 되고, 같은 원문이라도 파서·근거·범위의 수정은 새 초안 version이 됩니다. 원문 hash와 source ID는 바꾸지 않습니다. 조직의 발표를 해당 장관 개인의 행동으로 추정하지 않으므로 확인되지 않은 `personIds`는 빈 배열입니다.

worker의 raw-index 버전 순서와 `corrected`는 원문 변경 이력을 나타냅니다. 파서만 고친 경우 raw-index를 증가시키지 않습니다. 공개된 설명/근거 버전의 정정 판단과 최신 공개 버전 선택은 backend 관리자 검수가 별도로 처리합니다. 파서 개선을 이미 저장된 원문 hash에 덮어써서 immutable version 충돌을 일으키지 않습니다.

정책브리핑의 `.view_cont`가 문서 변환 iframe과 전재 안내문만 담는 경우 HTML에서 실제 발표 본문을 읽었다고 표시하지 않습니다. `bodyStatus=disclaimer_only` 또는 `unavailable`로 구분하고 **공식 제목·게시 메타데이터만 확인된 사건**을 남깁니다. 근거 excerpt는 원래 제목, locator는 `.view_title h1`이며 source hash/ID/최초 관측 시각은 바꾸지 않습니다. `coverage`에 본문·뷰어·첨부 원문 미수집과 상세 내용·실제 행동 미확인을 표시합니다. 이 기록을 발표 전체 내용의 검증으로 해석하지 않습니다.

메타데이터 사건은 `summary=null`이며 별도의 `scope=summary` blocked queue를 함께 남깁니다. `--prepare-summary`, provider payload 및 protocol 호출 모두 실질 본문 부재를 비용 예약/유료 HTTP 전에 차단합니다. 제목을 요약용 본문으로 대신 넣거나 HWP/PDF가 파싱된 것처럼 처리하지 않습니다. 파서 버전은 `official-html-v2`입니다.

## 공식 커넥터와 확인 범위

2026-10-07 공식 페이지를 실제로 읽어 확인한 구조를 사용했습니다.

| 출처 | 공식 목록/원문 경로 | 식별자·날짜·본문 |
|---|---|---|
| 대통령 브리핑 | [공식 브리핑](https://www.president.go.kr/briefings) | 목록 HTML `#sendForm`에서 게시판 파라미터를 읽고 공식 `/ajaxf/frBoard/bbsViewGalleryList.do`로 조회. `data.list[].BBS_CD`, `WRITE_DT/WRITE_DATE`; 상세 `.lineList_v .txtL/.txtInfo/.view_txt` |
| 대통령 연설문 | [공식 연설문](https://www.president.go.kr/speeches) | 동일 공개 게시판 AJAX, 폼의 `pBoardSeq`를 사용. 연설 날짜만으로 게시 시각을 추정하지 않음 |
| 대통령 공개일정 | [공식 일정](https://www.president.go.kr/schedule) | 공식 `/ajaxf/frSchedule/getSchedule.do?pSiteNo=2&pYear=...&pMonth=...`, `SCHEDULE_SEQ`, 발생일 `SCH_DT/SCH_TIME`, 등록일 `REG_DATE` epoch ms를 분리. 휴일 항목은 제외 |
| 총리실 보도자료 | [공식 보도자료](https://www.opm.go.kr/opm/news/press-release.do) | `a.c-board-title`, `articleNo`, 목록 담당부서/등록일. 상세 `.board-view-title-wrap h4`, `.board-view-txt` |
| 각 부처 발표 | [정책브리핑 보도자료](https://www.korea.kr/briefing/pressReleaseList.do) | `pressReleaseView.do?newsId=...`, 목록 `.source` 내 부처명. 상세 JSON-LD `datePublished`/`author.name`, `.view_title h1`, `.view_cont` |

정책브리핑 RSS는 사용하지 않습니다. 정책브리핑은 부처별 원문 전체를 보장하는 수집 경로가 아니며, 지원하는 공개 보도자료 범위만 수집합니다. 제목/목록 구조가 확인되지 않으면 명시적 실패 상태가 남습니다. 정책브리핑에서 HTML 본문을 확보하지 못하면 제목·게시 metadata와 본문 미확인/요약 차단을 함께 표시합니다. 사람의 공식 ID를 확인하는 연계와 개인별 표결·회의록 발언 추출은 아직 이 HTML 커넥터의 지원 범위가 아닙니다.

### 원문 이용 조건과 첨부

브리핑 원문 [확인 예시](https://www.president.go.kr/briefings/a2nTOLXS)는 공공누리 제4유형 안내를 실제로 포함합니다. worker는 비상업/변형금지 등 제한을 감지하면 `license_restricted`로 보존·검수 대기시키며 공개용 event를 만들지 않습니다. 명시적 자유이용 근거를 확인하지 못한 자료는 `license_unverified`, 공개일이 없는 자료는 `publication_date_missing`으로 남깁니다. 별도 이용 허락을 받은 사실을 worker가 임의로 가정하지 않습니다.

정책브리핑의 공공누리 제1유형 허락은 안내된 **텍스트 범위**만 사용합니다. 이미지/영상은 수집·재배포하지 않습니다. HWP/HWPX 첨부는 링크와 `unsupported_hwp`/`unsupported_hwpx`를 보존합니다. PDF는 `optional_pdf`로 표시하며 현재 자동 다운로드·OCR·내용 추출은 하지 않습니다. 운영 기록에는 이 상태 코드를 보존하고, 공개 설명에는 `한글(HWP)`, `한글(HWPX)`, `PDF`와 `내용 미확인`만 표시합니다. 제목·게시 정보만 확보했다면 본문과 실제 행동·시행·성과를 확인하지 못했다는 한계를 쉬운 한국어로 표시합니다. 공개 설명이 바뀌면 별도 Activity.version이 생성되며 원문 sourceVersion은 유지됩니다. 첨부 본문이 없는데 기사 전체를 분석한 것처럼 표시하지 않습니다.

## Java outbox와 선택적 AWS 연결

이 worker는 DB 스키마를 만들거나 Java 수집 프로세스를 바꾸지 않습니다. 다음 Java 테이블/상태를 전제로 합니다.

- `parliament_source_record_version(source_key, record_key, payload_hash, api_code, raw_payload, observed_at)`
- `parliament_processing_outbox(outbox_id, source_key, record_key, payload_hash, status, created_at, attempts, last_error)`; `PENDING/SENT/FAILED`

`payload_hash`는 현재 Java SHA-1 40자 또는 64자 digest를 허용합니다. 큐 메시지는 `outboxId/sourceKey/recordKey/payloadHash`만 담습니다. 원문·인증 키·개인 데이터는 큐 메시지에 넣지 않습니다.

`PARLIAMENT_PROCESSING_QUEUE_URL`을 명시하고 DB 접속 변수를 설정해야 실행할 수 있습니다. DB 기본 주소/포트는 `127.0.0.1:3307`, DB 이름은 `parliament`, 사용자와 비밀번호는 `PARLIAMENT_DB_USER/PARLIAMENT_DB_PASSWORD` 환경변수입니다. 원격은 `PARLIAMENT_DB_TLS_CA`를 사용해 인증서를 검증하고, `PARLIAMENT_DB_IAM=true`이면 RDS IAM 인증 토큰을 사용합니다. 비밀번호는 실행 환경에서 Secrets Manager 등으로 주입할 수 있습니다. AWS는 SDK 기본 IAM 역할/SSO credential chain과 `ap-northeast-2`를 사용하며 `AWS_PROFILE` 등 기존 환경을 그대로 따릅니다.

```sh
# 명시적 opt-in; 실제 SQS 전송과 outbox 상태 변경을 수행하므로 운영자가 실행
uv run --locked --no-editable parliament-worker relay-outbox --send --limit 20

# 원본 DB 버전을 로컬 보존하고 성공 후에만 큐 메시지를 삭제
uv run --locked --no-editable parliament-worker consume-versions --consume --output /tmp/parliament-source-versions
```

relay의 성공 상태 저장 전에 장애가 나면 중복 메시지가 생길 수 있습니다. consumer의 영속 SQLite 원장과 source/version 단위 처리는 이를 처리합니다. 실패한 consumer 메시지는 삭제하지 않습니다. consumer 원장·raw 출력 디렉터리를 재시작 때 유지해야 합니다. 재시도 5회 이후 relay는 `FAILED`를 보존하므로 운영자가 원인 확인 후 재처리해야 합니다. 실제 운영에서는 동일 파일 원장을 공유하는 단일 consumer로 시작합니다.

Java record 처리에서는 `BILL_ID/BILL_NAME/PROPOSE_DT`와 명시된 공식 `DETAIL_LINK/BILL_LINK/LINK_URL`가 있는 의안만 구조적 초안으로 변환합니다. 원안/수정가결, 대안반영폐기, 부결/폐기, 철회를 구분합니다. 미지원 API 기록은 원문과 `unsupported_record_type`를 보존하며 임의의 행동/표결 event를 생성하지 않습니다. MySQL JSON 보관 형식의 byte serialization은 원본 API 응답과 같다고 주장하지 않습니다. Java의 sourceVersion과 저장 snapshot의 SHA-256을 별도로 기록합니다. 의안 Activity.version도 `assembly-record-v2` mapper와 구조 payload의 별도 파생 해시입니다. `processed` 결과는 원문 hash에 덮어쓰지 않고 mapper/파생 내용별 64자 hash 파일로 남깁니다. 이미 ack된 원문의 새 mapper 재처리는 별도 운영 작업이며 자동 큐 재송신을 주장하지 않습니다.

`PARLIAMENT_RAW_BUCKET`이 설정된 상태에서 `collect ... --output ... --s3`를 명시하면 S3 raw adapter를 사용합니다. SDK IAM 역할/SSO로 인증하고 content-addressed object key, `IfNoneMatch=*`, server-side encryption을 사용합니다. 버킷 생성·공개·권한 변경은 하지 않습니다. S3/SQS 어댑터 검증은 fake client 테스트이며 실제 AWS 연결은 이 작업에서 실행하지 않았습니다.

## 설명 초안과 비용 제한

`SummaryProvider`는 명시적으로 주입할 수 있는 선택적 Python protocol입니다. `OpenAISummaryProvider` 어댑터는 아래의 명시적 옵션으로만 호출됩니다. 기본 실행에 자동 모델 호출은 없습니다. `generate_draft`는 사전 비용 추정액을 월간 원장에 예약하고, 출처 버전·evidence ID·정확한 원문 인용의 존재를 검증해 **초안만** 반환합니다. 이 검증은 문장의 의미적 진실성을 보장하지 않으므로 사람의 원문 대조가 필요합니다.

`ReviewLedger`는 서울 기준 하루 최대 3개 승인과 월간 비용 한도를 SQLite에 보존합니다. 월간 기본 한도는 100,000원이며 명시적으로 주입해 조정할 수 있습니다. provider 실패 시 보수적인 비용 예약을 유지합니다. 승인 identity에는 source version과 초안 digest를 포함하여 사용합니다. backend 공개 승인 제한과는 별도 원장이므로 실제 공개의 기준은 backend 관리자 검수입니다.

초안 한 줄 요약·claim·evidence를 별도 로컬 검수 큐로 저장합니다. 전체 회의록 의미 분석, OCR/HWP 파서, 수익화·결제는 이번 worker의 구현 범위가 아닙니다.

### 명시적 OpenAI 요약 초안

선택적 `OpenAISummaryProvider`는 [공식 Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)와 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) 계약을 사용합니다. 모델 기본값은 없습니다. 운영자는 Chat Completions의 developer 메시지·JSON Schema·`max_completion_tokens`를 지원하는 모델을 직접 설정해야 합니다. 호스트는 `https://api.openai.com/v1/chat/completions`로 고정하고 임의 compatible endpoint와 인증 리디렉션을 허용하지 않습니다.

필수 환경변수는 `OPENAI_API_KEY`, `PARLIAMENT_SUMMARY_MODEL`, `PARLIAMENT_SUMMARY_INPUT_KRW_PER_MILLION`, `PARLIAMENT_SUMMARY_OUTPUT_KRW_PER_MILLION`, `PARLIAMENT_REVIEW_LEDGER`입니다. 비용 원장은 소스별 output과 분리된 **공유 경로**로 설정합니다(운영 예: `/data/review.sqlite3`). 모든 source와 반복 실행에 같은 경로/예산을 적용하고 파일과 디렉터리를 재시작 시 유지해야 합니다. 다른 원장을 지정하는 것은 별도 예산을 만드는 운영 설정 변경입니다.

토큰 단가는 운영자가 검증하여 넣는 양의 KRW 값이며 현재 시장 가격을 주장하지 않습니다. 입력 단가는 캐시 할인을 가정하지 않은 prompt 전체의 보수적 단가, 출력 단가는 configured model의 reasoning 토큰을 포함하는 completion 전체 단가로 설정합니다. 환율/세금 등 청구 비용도 운영자가 보수적으로 반영해야 합니다. 공급자의 cached token 세부값을 할인으로 자동 반영하지 않습니다. 월간 모델 비용 한도는 `PARLIAMENT_SUMMARY_MONTHLY_BUDGET_KRW`(기본 100000)입니다. 키·공유 원장·단가가 빠지거나 음수/NaN/무한대이면 호출 전에 실패합니다.

```sh
# 이 옵션을 운영자가 직접 실행하면 실제 유료 모델 요청을 수행할 수 있습니다.
# 이번 구현 검증에서는 fake HTTP만 사용했으며 실제 호출은 하지 않았습니다.
uv run --locked --no-editable parliament-worker collect --source korea --output /tmp/parliament-review --prepare-summary --summary-limit 3
```

이 옵션은 `--output`이 필수이고 `--publish`와 함께 쓸 수 없습니다. 한 번에 1~3개 초안만 준비합니다. developer 규칙과 JSON `untrustedSource`로 원문을 구분하며, 원문 지시는 명령으로 취급하지 않습니다. 외부 지식·사람 이름·숫자·정책 단계를 사실 테이블에 자동 반영하지 않습니다. 한 줄 요약도 첫 문장의 인용과 연결되어야 합니다. 모든 문장은 정확한 evidence ID/source hash/원문 excerpt와 연결되고 잘못된 인용은 `blocked`로 저장합니다. 기계 검증이 통과해도 의미·이름·숫자·발표와 실제 시행의 차이는 사람이 확인해야 합니다.

모델 요청 전에 최대 completion과 보수적인 request-byte 기반 예산을 영속 예약합니다. 반환 usage의 prompt/completion 토큰에 설정 단가를 적용해 정산하며 이것은 제공업체 청구서의 확정 비용은 아닙니다. usage 미제공·요청 실패·파싱 실패이면 보수적인 예약이 남습니다. 예상을 넘은 실측 비용도 원장에 기록하고 해당 월 추가 요청을 차단합니다. 운영자가 비용/단가와 실제 청구를 확인하여 별도로 reconciliation 해야 하며 자동 초기화·재시도는 하지 않습니다.

초안은 `summary_drafts/<source identity>/<source hash>/<draft hash>.json`에 불변 저장합니다. 원문 hash, parser/prompt 버전, 요청한 모델과 반환 snapshot 모델, response ID, usage, 당시 설정한 input/output 단가와 비용을 기록합니다. 같은 source/parser/prompt/model/request 내용은 로컬 결과를 재사용하므로 정상 완료된 요청의 반복 실행이 자동 재과금하지 않습니다. 입력 본문은 UTF-8 16000바이트로 제한하고 일부만 전달되면 `sourceTextTruncated`를 표시합니다. 응답은 128KiB이며 HTTP I/O timeout과 스트림 deadline을 적용합니다. DNS 자체의 시스템 지연을 포함하는 완전한 wall-clock 보장을 주장하지 않습니다. 초안 생성은 단일 worker/운영 `flock`으로 직렬화해야 합니다. 캐시 인덱스 저장 전 중단된 요청은 자동으로 재실행하지 말고 잔여 예약을 먼저 확인합니다.

이 어댑터는 실제 HTTP 계약 코드를 fake transport로 실행해 검증했습니다. 실제 키 권한, 선택 모델의 지원 여부·계정 한도·응답 품질은 미검증 상태입니다. 초안은 자동 공개·승인·메일 발송되지 않습니다.

## 로그인/다이제스트 메일

Java `tracking_mail_outbox`와 `tracking_user`, `tracking_login_token` 테이블을 사용합니다. 새 테이블이나 credentials 파일을 만들지 않습니다. 이메일 주소는 backend의 ASCII local-part 문자 범위, 64자 한도, 소문자 정규화를 따르고 header control 문자는 거절합니다. DB 접속 환경변수는 위 outbox 어댑터와 같습니다. `TRACKING_PUBLIC_BASE_URL`은 backend와 동일한 고정 web origin이어야 하며 원격 HTTPS/로컬 loopback만 허용합니다. 링크는 그 origin의 `/auth/verify`, `/unsubscribe` 및 version이 고정된 `/activities/{id}?version={version}`만 생성합니다. 큐의 임의 활동 URL은 사용하지 않습니다.

```sh
# 기본: SES client를 만들지 않고 mode 0600 EML 미리보기만 저장
uv run --locked --no-editable parliament-worker mail --output /tmp/parliament-private-mail --limit 20

# 실제 발송 가능: 운영자가 verified sender와 IAM 권한을 먼저 설정해야 함
# 이 구현 작업에서는 실행하지 않았습니다.
uv run --locked --no-editable parliament-worker mail --output /tmp/parliament-private-mail --limit 20 --send
```

미리보기에는 설정한 `PARLIAMENT_MAIL_FROM` 또는 `preview@parliament.invalid`를 사용합니다. 실제 `--send`에는 `PARLIAMENT_MAIL_FROM`이 필수이며 운영자가 SES에서 검증된 identity인지 사전에 확인해야 합니다. 어댑터가 검증된 sender를 생성하거나 AWS sandbox/계정 한도를 해제하지 않습니다. SESv2는 SDK IAM/SSO chain과 서울 리전을 사용하고 credentials를 하드코딩하지 않습니다.

스풀 디렉터리는 0700, `.eml` 파일은 0600으로 저장하고 symlink root를 거절합니다. `mail_id` UUID와 안정적인 Message-ID를 사용해 동일 파일을 재생성하지 않습니다. preview EML은 output root, 실제 발송용 EML은 `output/delivery`에 불변 보존합니다. EML에는 이메일 주소와 로그인/해지 토큰이 있으므로 공개 웹 디렉터리로 노출하지 않아야 하며 접근 제한과 짧은 보관 정책은 운영 환경에서 설정합니다. 로그에는 메시지 개수/오류 종류만 남깁니다.

| 상태 | 처리 |
|---|---|
| `queued` | 처리 대상. 기본 preview는 유효한 행을 이 상태에 유지 |
| `cancelled` | 만료/사용된 로그인, 해지·빈도 변경·수신자 변경·미검증 digest 또는 잘못된 payload; 재시도 대상에서 제외 |
| `sending` | user 행 → mail 행 잠금에서 검증 후 **SES 요청 전 별도 커밋한** 상태. 프로세스 중단 시 수동 확인 필요 |
| `sent` | 단일 SES 요청 성공 이후 커밋한 최종 상태. 다음 배치에서 다시 보내지 않음 |
| `uncertain` | 요청 실패/불명확한 응답/커밋 불확실성. 자동 재시도하지 않고 운영자 확인 |

실제 전송은 user 행을 다시 잠그고 현재 `email_enabled`, verified 상태, 빈도, 수신자, unsubscribe token 또는 로그인 token의 실제 만료/사용 여부를 확인합니다. 잠금 대기 이후에도 현재 시각을 다시 평가합니다. SES 요청 동안 user 잠금을 유지하므로 해지 처리가 먼저 끝나면 전송을 취소하고, 전송이 먼저 잠금을 획득한 경우 진행 중인 단일 요청 뒤에 해지가 처리됩니다. 이미 진행 중인 외부 요청을 취소했다는 보장은 없습니다.

SES에는 client idempotency key가 없으므로 SDK 자동 retries도 `total_max_attempts=1`로 끕니다. stable mail ID는 MIME과 SES tag에 함께 남지만 공급자의 전달 중복 제거를 보장하지 않습니다. `sending`/`uncertain`을 queued로 자동 되돌리는 코드가 없습니다. `uncertain`은 exit 1로 보고합니다. 운영자는 공급자 기록과 해당 mail ID를 대조하고 개별 결과를 수동 정리해야 합니다. SES 수락은 실제 받은편지함 도착을 뜻하지 않으며 bounce/complaint/event callback 처리와 자동 EML 정리는 이번 어댑터 범위 밖입니다.

### worker 컨테이너

`worker/Dockerfile`은 Python 3.12.11 및 uv 0.10.4를 사용하고 `uv.lock`의 aws dependency group까지 설치합니다. uid/gid 10001의 비루트 사용자로 실행하며 기본 명령은 도움말입니다. 운영자가 `/data` 볼륨의 소유권/권한을 uid 10001에 맞춰야 합니다.

Compose/systemd용 명령은 `collect --source ... --output /data/...`, `relay-outbox --send --limit 20`, `consume-versions --consume --output /data/source-versions`, `mail --output /data/private-mail --limit 20`입니다. SES 실제 발송 작업에만 `mail ... --send`를 추가합니다. summary는 공유 `PARLIAMENT_REVIEW_LEDGER=/data/review.sqlite3`와 단일 worker/`flock`을 사용해 별도 명시적 작업으로 켜고 야간 기본 작업에 유료 옵션을 넣지 않습니다. Docker 이미지 자체의 실제 빌드와 운영 네트워크/AWS 연결은 상위 작업의 통합 검증 대상입니다.
