# GitHub 코드 관리

## 소스와 운영 입력

저장소는 코드·검사·합성 fixture·예시 설정의 기준입니다. `.local/`, `.env`, `worker/manifests/*.json`, 실제 뉴스 수집본, 웹 해설 원고, Java의 실제 `issue-readings.json` 공개 묶음, 운영 문서·캠페인 원장은 Git에서 제외합니다. 로컬 파일은 삭제하지 않습니다.

새 clone:

```bash
python3 scripts/bootstrap_repository.py
npm --prefix web ci
npm --prefix mobile ci
cd worker
uv sync --locked --all-extras
```

초기화는 `*.example.json`에서 없는 입력만 생성합니다. 웹 예시는 사람 검토 전 합성 원고, 뉴스 예시는 빈 수집 상태입니다. 실제 내용을 공개하려면 원고·신원·역할·근거·이용 조건과 정확한 공개 버전을 별도로 확인해야 합니다. CI/브라우저 검사는 운영 입력 대신 고정 합성 fixture를 사용합니다.

## 변경 절차

작업별 Issue에 사용자 행동·담당·선행 조건·완료 기준을 기록하고 해당 브랜치와 PR을 연결합니다. 변경은 `feat/`, `fix/`, `hotfix/`, `chore/` 브랜치에서 수행합니다. 커밋은 Conventional Commit 형식을 사용합니다.

```bash
git switch -c feat/short-task-name
# 변경·검증 후 파일을 명시해서 추가합니다.
git add path/to/source path/to/test
python3 scripts/check_repository.py
git diff --cached --check
git commit -m "feat: describe the resulting user behavior"
git push -u origin HEAD
```

한 작업의 공개 가능한 파일만 추가하고 `git add -f`로 비공개 경계를 우회하지 않습니다. 검증 이후의 새 변경은 별도 커밋으로 구분합니다. 운영자 문서는 로컬에 남기고 공개 Issue에는 작업 관리에 필요한 최소 내용만 씁니다.

## 자동 검사

PR과 개발 브랜치 push에서 다음 검사를 실행합니다.

- Repository hygiene: 비공개 경로·예시 초기화·Git 이력 비밀키 검사
- Java tests: JDK17, Gradle check·라인 커버리지 80%·애플리케이션 빌드, 격리된 Testcontainers
- Python tests: lock 파일 기반 worker 검사와 운영 도구 합성 검사
- Web checks: 의존성 보안 검사·단위 검사·타입 검사·Next.js 빌드
- Mobile checks: 의존성 보안 검사·단위 검사·Vite 빌드·Chromium 흐름 검사

수동 Galaxy visual workflow는 후보 캡처/기존 검토 baseline 비교에 사용합니다. 테스트 실행 중 검증 기준을 낮추거나 baseline을 자동 승인하지 않습니다. 합성·브라우저 검사를 실물 Galaxy나 실제 정치 자료의 공개 승인으로 표현하지 않습니다.

CI와 GitHub 저장소 설정은 코드 품질 관리이며 서버·앱스토어·AWS 배포를 자동 수행하지 않습니다. 로컬 `.env`와 실제 원고/수집 입력은 개발자가 기존 보안 절차로 별도 준비합니다.
