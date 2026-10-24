# 의정의 흐름 · 갤럭시 앱

흰색 배경과 파란색 포인트로 정부·국회 공개 기록을 읽는 React + Capacitor Android 앱입니다. 기존 Java / Next.js 공개 API의 활동 데이터 계약과 출처 검증을 공유합니다. 기존 웹이나 백엔드의 동작을 바꾸지 않습니다.

## 설치 파일과 화면

- 홈·모션 개선 APK: `artifacts/parliament-flow-home-refresh.apk`. [조사·설계와 검증 결과](../docs/product/home-focus-motion-verification.md).
- 테스트용 APK: `artifacts/parliament-flow-debug.apk` (Android 7 / API 24 이상, 앱 ID `dev.parliament.flow`, 버전 0.1.0).
- 홈·탐색·관심 선택·설정: `artifacts/*-final.png`.
- Android 실제 실행 화면: `artifacts/android-home.png`.
- 구현 계획: `../docs/plans/2026-10-08-galaxy-app.md`.
- 확인 결과와 제한: `../docs/product/galaxy-app-verification.md`.

APK를 갤럭시로 복사하고 파일 앱에서 열어 설치합니다. Android가 설치 출처 허용을 요청하면 해당 설치를 사용자가 직접 승인합니다. 이 파일은 개발용 디버그 서명이며 Play Store 배포용 서명과 심사를 대신하지 않습니다.

## 실행과 빌드

```sh
cd mobile
npm ci --ignore-scripts
npx playwright install chromium
npm run dev
npm run qa
npm run android:build
```

브라우저 주소는 `http://127.0.0.1:14200`입니다. Node 22 이상이 필요합니다. Android 빌드는 JDK 21, Android SDK Platform 36 / Build Tools, 그리고 SDK 라이선스가 필요합니다. Android Studio를 사용하는 다른 컴퓨터에서는 `JAVA_HOME`과 `ANDROID_HOME`을 해당 설치 경로로 설정하세요. 이번 작업에서 준비한 프로젝트 내부의 `../.local/java`, `../.local/android-sdk`는 빌드 스크립트가 자동으로 찾습니다. `.local`의 설치 도구·SDK·JDK는 저장소에 포함하지 않습니다.

## 화면과 기능

- **홈:** 첫 기록을 강조하는 집중 카드, 펼칠 수 있는 주제·유형 필터, 간결한 후속 기록, 전체/관심 피드, 4개 주제 필터, 기록 유형 필터, 다음 기록 읽기. 관심 피드는 읽어 온 공개 피드에서 선택한 주제와 일치하는 항목입니다. 다음 페이지로 조회 범위를 확장할 수 있습니다.
- **탐색:** 키워드 검색, 주제 선택, 검색 조건 초기화.
- **상세:** 단계, 정정 여부, 원문 발췌·위치·버전, 공식 출처, 발생/공개/수집/변화 날짜, 공개된 표결 및 자료 범위.
- **저장:** 최대 50개 기록 ID를 기기에 저장합니다. 실제 기록은 재실행 때 API로 다시 조회합니다. 예시와 실제 저장 목록은 분리하고 서버 변경 시 실제 목록을 비웁니다.
- **설정:** 큰 글자, 움직임 줄이기, 네이티브 저장 진동, 관심 주제, 자료 모드·서버 주소.
- **이동:** 방향 있는 화면 전환, 움직이는 메뉴 선택 표시, 관심 창 열기·닫기, 저장 피드백. View Transitions가 없으면 Web Animations로 전환하며 OS와 앱의 움직임 줄이기를 존중합니다.
- **Android:** 앱 아이콘, 흰색 시작화면, 밝은 시스템 바, 안전 영역, 네이티브 뒤로가기와 외부 원문 브라우저.

알림은 준비 중임을 표시합니다. 푸시·이메일 발송이나 앱 계정 인증은 포함하지 않습니다. 기기 관심 목록을 서버로 업로드하지 않습니다.

## 실제 자료 연결

초기 모드는 **디자인 미리보기**입니다. 예시는 정치 사건을 설명하는 실제 데이터가 아니라 화면 구성 설명입니다. 서버 오류 때 미리보기로 자동 전환하지 않습니다.

설정의 **공개 API 서버 주소**에 기존 Next.js 웹이 제공하는 HTTPS origin을 넣고 **서버 연결하기**를 누릅니다. 서버는 `/api/v1/activities`, `/api/v1/activities/{id}`, `/api/v1/search`의 기존 공개 계약을 제공해야 합니다. 해당 서비스를 운영하지 않았다면 API가 응답하기 전까지 실제 기록은 열리지 않습니다. 자격증명·경로·쿼리·HTTP 주소는 거부합니다.

네이티브 앱은 CapacitorHttp를 사용하고 리디렉션을 따라가지 않습니다. 브라우저에서 별도의 서버를 조회할 때는 그 서버의 CORS 허용이 필요합니다. 기존 Next.js 서버가 다른 브라우저 origin을 허용하지 않는 경우 모바일 브라우저의 실제 조회는 오류로 표시되며, 네이티브 앱과 동일하게 연결된 것으로 설명하지 않습니다. 수집기의 관리자 API나 관리자 키는 사용하지 않습니다.

## Agentic UI QA

```sh
npm run qa                 # 핵심 테스트 → 타입/제품 빌드 → 브라우저 조작
npm run qa:repair          # 실패할 때만 Codex 수정, 최대 3회 → 같은 검사 재실행
npm run format:check
npx playwright show-report
```

`qa:repair`는 로컬에 고정 설치한 Codex CLI를 호출하며 기존 CLI 로그인과 사용량이 필요합니다. CLI 실행 방식은 [OpenAI 공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode)에 맞췄습니다. 자동 수정은 `workspace-write`로 실행하고 테스트·E2E·설정·패키지·검증 스크립트 SHA-256을 전후 비교합니다. 보호 대상이 변경되면 `contract-changed`로 실패 처리하며 사용자의 변경을 임의로 되돌리지 않습니다. 테스트 파일을 읽기 전용 파일 시스템으로 격리한 것은 아니므로 이 검사는 변경 탐지 장치입니다.

수정 에이전트에는 실패 로그와 가능한 최종 화면을 제공하며, 수정 권한은 `src/` 및 `android/app/src/main/` 범위로 지시합니다. 전체 성공 시 모델 호출을 생략합니다. 큰 UX 변경은 제안만 남깁니다. 검증 로그, 수정 보고서, 시각 자료와 성능 trace는 `artifacts/qa/<시각>/`, `artifacts/`, `test-results/`, `playwright-report/`에 저장됩니다. 로그·화면은 에이전트가 검토하는 근거입니다. 일반 `qa`가 미적 UX 품질을 독립적인 Vision 모델로 채점하는 것은 아닙니다.

브라우저 검증은 클릭·검색 입력·필터·페이지 이동·저장 지속성·모달 Escape/초점 복원·장애/빈 결과/잘못된 응답·360/412/768px·OS 움직임 줄이기를 다룹니다. 영상과 Playwright trace를 남기고 CDP로 렌더링 trace 및 타이밍 지표를 수집합니다. 개선 후 정적 스크린샷은 `artifacts/home-refresh/home-after.png`에 문서 애니메이션 완료를 기다려 저장하고, 이동 중간 프레임과 영상도 따로 보존합니다. 물리적 갤럭시 FPS·진동·키보드·배터리·실사용자 UX 결과를 이 자료에서 추정하지 않습니다.
