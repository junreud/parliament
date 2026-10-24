# 코드 변경과 검증

1. `AGENTS.md`와 [GitHub 작업 절차](docs/development/github-workflow.md)를 읽습니다.
2. `feat/`, `fix/`, `hotfix/`, `chore/` 브랜치에서 한 사용자 행동과 완료 조건을 정합니다.
3. `python3 scripts/bootstrap_repository.py`로 새 clone의 예시 입력을 준비합니다. 기존 로컬 파일은 덮어쓰지 않습니다.
4. 변경에 맞는 실패 검사·수정·회귀 검증을 수행합니다. Python은 타입 힌트·Google 스타일 docstring·Black/isort를 적용합니다.
5. `python3 scripts/check_repository.py`와 비밀키 검사를 통과한 공개 소스만 Conventional Commit으로 커밋합니다.
6. PR에 연결 작업·검증 결과·남은 조건·보안 검토를 작성합니다. CI 통과와 실제 서비스/실물 기기/사용자 검증은 별개입니다.

운영자의 `.env`, `.local`, 원문·후보·명부·검수 자료, 배포 키, 캠페인 운영 원장과 미디어는 커밋하지 않습니다. 테스트는 고정 합성 fixture를 사용하며 실제 운영 파일을 수정하지 않습니다.

예시 입력은 공개 승인이 아닙니다. 새 수집·외부 메시지·원고 공개·배포·과금 작업은 해당 작업의 실제 권한과 검토 범위에서 수행합니다.
