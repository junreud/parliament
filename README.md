# Parliament Data Platform

국회 관련 공개 API의 원문과 인물·직위·대표 SNS를 로컬 MySQL에 정규화해 쌓기 위한 개인 프로젝트입니다. 실제 적재는 기본적으로 잠겨 있으며, 데이터베이스와 자격정보는 로컬 환경에만 보관합니다.

## 현재 준비 범위

- 열린국회정보 공개 API 카탈로그 272개를 스냅샷으로 관리합니다.
- 일반 데이터 269개는 사전 점검 및 페이지 적재 대상입니다.
- 영상 관련 3개 API는 `VIDEO / EXCLUDED`로 고정해 호출과 적재에서 제외합니다.
- 모든 응답 행의 원문 JSON과 해시를 보존하고, 체크포인트로 중단 지점부터 재개합니다.
- 구조화된 인물 필드에서 국회의원, 정부 공직자, 기타 인물 후보를 분류합니다.
- 국회가 제공한 SNS 필드를 X, YouTube, 네이버 블로그, Facebook, Instagram, Threads, TikTok, Telegram의 정규 URL로 매핑합니다.
- 외부 키가 확인된 국회의원만 확정 식별자로 병합합니다. 이름만 있는 사람은 자동 병합하지 않고 `PROVISIONAL_NAME_MATCH`로 둡니다.

### 인물 분류 원칙

| 종류 | 판단 근거 | 식별 방식 |
|---|---|---|
| `LEGISLATOR` | 국회의원 데이터 소스이며 의원 외부 ID가 있음 | `assembly-member:{외부 ID}` |
| `PUBLIC_OFFICIAL` | 국무총리·장관·차관·청장 등 공직 직함이 명시됨 | 이름·직위·소속 기반 후보 키 + 직위 이력 |
| `OTHER` | 증인·참고인·전문가 등 위 두 근거가 없음 | 이름·직위·소속 기반 후보 키, 추후 검수 |

이름만 같은 사람을 동일 인물로 확정하지 않습니다. 자유문 본문에만 등장하는 인물의 NER(개체명 인식)와 영상 분석은 이번 단계의 범위가 아닙니다. 자유문 원문은 `parliament_source_record.raw_payload`에 남으므로 후속 분석기를 안전하게 붙일 수 있습니다.

## 안전장치

다음 세 조건이 모두 충족되어야 실제 DB 쓰기 요청이 동작합니다.

1. `PARLIAMENT_INGESTION_ENABLED=true`
2. `PARLIAMENT_INGESTION_WRITE_ENABLED=true`
3. `/run` 요청 본문의 `confirmWrite=true`

사전 점검(`/preflight`)은 외부 API 한 페이지만 읽고 DB에는 쓰지 않습니다. API 키와 관리 키는 환경변수로만 주입하며 저장소·응답·로그에 기록하지 않습니다. HTTP 클라이언트는 `https://open.assembly.go.kr`만 허용합니다.

## 로컬 준비

요구사항은 Java 17과 Docker입니다.

```bash
cp .env.example .env
# .env의 네 키를 직접 변경
set -a
source .env
set +a
docker compose up -d mysql
./gradlew bootRun
```

`.env`는 Git에서 제외됩니다. MySQL은 로컬 `3307` 포트에 뜨며 최초 볼륨 생성 때 [schema-parliament.sql](src/main/resources/sql/schema-parliament.sql)을 적용합니다.

## 사전 점검만 실행

아래 요청은 DB 적재를 수행하지 않습니다.

```bash
curl -X POST http://localhost:8080/admin/ingestion/parliament/preflight \
  -H "Content-Type: application/json" \
  -H "X-Parliament-Ingestion-Key: $PARLIAMENT_INGESTION_ADMIN_KEY" \
  -d '{"sourceKeys":["allnamember","negnlnyvatsjwocar"],"pageSize":10,"maxPages":1,"confirmWrite":false}'
```

`sourceKeys`를 빈 배열로 보내면 영상 제외 후 활성화된 전체 카탈로그를 대상으로 합니다. 처음에는 의원 기본정보 `allnamember`와 SNS `negnlnyvatsjwocar`처럼 작은 묶음으로 확인하는 것을 권장합니다.

## 실제 적재 직전의 마지막 단계

실제 적재는 이 구현 작업에서 실행하지 않습니다. 실행하려면 운영자가 직접 쓰기 플래그를 켜고 애플리케이션을 다시 시작한 다음 `/admin/ingestion/parliament/run`에 `confirmWrite=true`를 보내야 합니다. 페이지 단위 트랜잭션이 성공한 뒤에만 체크포인트가 이동합니다.

## 데이터 모델

- `parliament_person`: 인물의 현재 정규화 이름, 분류, 식별 상태
- `parliament_person_identifier`: 열린국회정보 의원 ID 등 외부 식별자
- `parliament_legislator_term`: 의원별 국회 대수 이력
- `parliament_legislator_status`: 최신 공식 명부를 근거로 한 `CURRENT`/`FORMER` 상태
- `parliament_person_position`: 출처 레코드에 근거한 직위·소속 관찰 이력
- `parliament_social_account`: 플랫폼별 대표 URL과 검증 근거
- `parliament_source_record`: 소스별 원문 JSON 및 내용 해시
- `parliament_record_person`: 원문 레코드와 인물의 연결
- `parliament_ingestion_checkpoint`: 소스별 다음 페이지와 완료 상태

현역 의원은 `국회의원 인적사항` 최신 명부(`nwvrqwxyaytdsfvhu`)에 포함된 의원으로 판정합니다. 단순히 제22대 이력이 있다는 이유만으로 현역 처리하지 않습니다. 조회할 때는 `parliament_current_legislator`와 `parliament_former_legislator` 뷰를 사용합니다.

기존 DB는 스키마 확장과 재분류를 분리해 적용합니다.

```bash
mariadb parliament < src/main/resources/sql/migrations/002-legislator-term-status-up.sql
mariadb parliament < src/main/resources/sql/migrations/003-rebuild-legislator-classification.sql
```

재분류 SQL은 파생 테이블만 트랜잭션 안에서 다시 만들며 반복 실행할 수 있습니다. 최신 명부 API를 완전 적재한 뒤 실행해야 합니다.

## 검증

```bash
./gradlew test
```

테스트는 영상 제외, 인물 분류, SNS URL 허용목록, API 애플리케이션 오류 처리, dry-run 무쓰기, 이중 쓰기 잠금, 실제 MySQL 스키마·트랜잭션·체크포인트를 확인합니다. Docker 엔진이 실행 중이어야 합니다.

## 데이터 출처와 갱신

카탈로그 파일은 열린국회정보의 `OPENSRVAPI` 목록을 바탕으로 하며, 발견 코드 보강에는 MIT 라이선스의 `hollobit/assembly-api-mcp` 공개 카탈로그를 참고했습니다. 스냅샷 날짜와 참조 URL은 [open-assembly-sources.json](src/main/resources/parliament/open-assembly-sources.json)에 기록되어 있습니다. 외부 API 목록과 필드 계약은 변할 수 있으므로 실제 적재 전에 반드시 `/preflight` 결과로 재확인해야 합니다.
