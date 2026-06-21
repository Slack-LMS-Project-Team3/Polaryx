# Polaryx (Slack-LMS)

Slack을 모티브로 한 **학습 관리 시스템(LMS)** 형태의 실시간 협업 메신저입니다.
워크스페이스 · 채널(탭) · 다이렉트 메시지 · 캔버스 · 파일 공유 · 실시간 알림을 제공합니다.

> 사내/팀 코드 저장소 기준 문서입니다. 운영 도메인: `polaryx.net`, `jungle-lms.site`

---

## 🧩 주요 기능

- **소셜 로그인** — Google / GitHub OAuth 2.0 기반 인증, JWT(Access/Refresh) 발급
- **워크스페이스 & 멤버** — 워크스페이스 단위 그룹, 멤버·역할(Role) 관리
- **채널(탭) & 섹션** — 탭/서브탭/섹션으로 구성되는 메시지 공간
- **메시지** — 실시간 채팅(WebSocket), 메시지 저장/수정, 링크 미리보기
- **다이렉트 메시지(DM)** — 1:1 및 그룹 DM
- **캔버스** — 문서형 협업 공간
- **파일 업로드** — AWS S3 Presigned URL 기반 업로드
- **알림** — Web Push(VAPID) + SSE(Server-Sent Events) 실시간 알림

---

## 🏗️ 기술 스택

### Backend (`/BE`)
- **FastAPI** (Python 3.12) — 라우터/서비스/리포지토리/도메인 레이어드 아키텍처
- **MySQL** — 주 데이터 저장소 (커넥션 풀)
- **MongoDB** — 비정형 데이터
- **Redis** — 캐시 / 세션 / 실시간 처리
- **인증** — `python-jose`, `PyJWT` 기반 JWT
- **인프라** — AWS S3, Web Push(`pywebpush`), WebSocket, SSE

### Frontend (`/FE`)
- **Next.js 15** (App Router, Turbopack) + **React** + **TypeScript**
- **Tailwind CSS** + **Radix UI** + **shadcn/ui**
- **Tiptap** 기반 에디터, Zustand 스토어
- AWS SDK(S3), Web Push 구독

### 배포
- Docker 이미지 → AWS ECR → EC2(`docker-compose`)

---

## 📂 프로젝트 구조

```
Polaryx/
├── BE/                         # FastAPI 백엔드
│   └── app/
│       ├── main.py             # 앱 진입점, 라우터/CORS/예외핸들러 등록
│       ├── router/             # API 엔드포인트 (auth, message, workspace, s3 ...)
│       ├── service/            # 비즈니스 로직
│       ├── repository/         # DB 접근 (SQL 쿼리)
│       ├── domain/             # 도메인 모델
│       ├── schema/             # 요청/응답 Pydantic 스키마
│       ├── core/               # 보안(security.py), 예외 핸들러
│       ├── util/database/      # MySQL/MongoDB/Redis 커넥션
│       ├── config/             # 환경설정(Settings)
│       └── sql/                # DDL / 시드 데이터
├── FE/                         # Next.js 프론트엔드
│   ├── app/                    # App Router 페이지
│   ├── apis/                   # API 호출 모듈
│   ├── components/ store/ hooks/ lib/ utils/
│   └── public/
├── docker-compose.backend.yml
└── docker-compose.frontend.yml
```

---

## 🚀 로컬 실행

### 사전 준비
- Python 3.12, Node.js 20.19+ (frontend Vitest/Vite toolchain)
- MySQL / MongoDB / Redis 인스턴스
- 루트에 `.env` 파일 작성 (아래 환경변수 참고)

### Backend
```bash
cd BE
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app
# http://localhost:8000  (Health: GET /api/health)
```

### Backend Regression Suite
로컬에서는 아래 명령으로 auth/realtime, security regression suite 및 service-level unit suite를 실행합니다.

```bash
cd BE
.venv/bin/python -m unittest tests.regression.test_auth_realtime_regression tests.regression.test_security_access_control_regression tests.unit.test_service_business_rules
```

security regression suite만 단독으로 확인할 때는 아래 명령을 사용합니다.

```bash
cd BE
.venv/bin/python -m unittest tests.regression.test_security_access_control_regression
```

CI에서는 `BE/requirements.txt` 설치 후 같은 suite들을 시스템 Python으로 실행합니다.

```bash
python -m pip install -r BE/requirements.txt
cd BE
python -m unittest tests.regression.test_auth_realtime_regression tests.regression.test_security_access_control_regression tests.unit.test_service_business_rules
```

이 테스트 파일들은 safe default env values를 내부에서 설정하고 DB/Redis/AWS 접근을 stub 처리하므로, 이 regression/service unit suite에는 MySQL, Redis, AWS, OAuth, and real secrets are not required. service-level unit suite는 message/reaction, notification, role, workspace membership, 순수 access-control helper의 비즈니스 규칙을 DB/Redis 없이 검증합니다. 현재 프로덕션 코드에서 아직 막히지 않은 DB reset, S3 presigned URL, workspace/tab/member access-control 케이스는 `unittest.expectedFailure`로 스테이징되어 있으며, 실제 보안 수정이 들어오면 해당 marker를 제거해야 합니다.

### Frontend
로컬 개발 서버와 배포 전 품질 체크는 아래 명령을 사용합니다.

```bash
cd FE
npm install
npm run dev
# http://localhost:3000
```

```bash
cd FE
npm run lint
npm run build
npm run test
```

frontend test suite는 Vitest + React Testing Library + jsdom 기반이며, API network, Next router, OAuth callback, browser storage 상태를 mock 처리합니다. CI에서는 lockfile 기준 설치를 위해 `npm ci` 후 `npm run lint`, `npm run build`, `npm run test`를 각각 독립 quality gate로 실행합니다.

### Windows 통합 실행
```powershell
./start-dev.ps1   # FE/BE 동시 기동
```

### Docker
```bash
docker compose -f docker-compose.backend.yml up -d
docker compose -f docker-compose.frontend.yml up -d
```

---

## 🔐 환경변수 (`.env`)

`.env`는 **절대 커밋 금지** (`.gitignore`에 포함됨). 필요한 키 목록:

```
SECRET_KEY=                 # JWT 서명 키 (강력한 랜덤 값)
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_MINUTES=60000
# DB
RDB_HOST= RDB_PORT= DB_USER= DB_PASSWORD= DB_NAME=
NOSQL_HOST= NOSQL_PORT= NOSQL_URL=
REDIS_HOST= REDIS_PORT= REDIS_PASSWORD= REDIS_DB=
CONNECTION_TIMEOUT=
# OAuth
GOOGLE_CLIENT_ID= GOOGLE_CLIENT_SECRET= GOOGLE_REDIRECT_URI=
GITHUBS_CLIENT_ID= GITHUBS_CLIENT_SECRET= GITHUBS_REDIRECT_URI=
# AWS S3
AWS_REGION= AWS_BUCKET_NAME= AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY=
# Web Push (VAPID)
VAPID_PUBLIC_KEY= VAPID_PRIVATE_KEY= VAPID_EMAIL=
```

---

## 🩺 보안 체크

배포 전 인증 없는 DB 초기화 엔드포인트, 미인증 라우터, 토큰 처리, 외부 서비스 키 노출 여부를 반드시 확인하세요.

---

## 🤝 협업 규칙

### 0. Reset / Rebase 금지 (중요!)
공유 브랜치에서 강제 푸시·리베이스 금지. 변경 전 팀과 협의.

### 1. 브랜치 전략
- 🔒 `main` 브랜치에 **직접 push 금지** — 항상 배포 가능한 상태 유지
- 모든 기능은 개별 브랜치에서 작업 후 Pull Request로 병합
- 브랜치 네이밍: `<기능명>` (예: `login-form`)

### 2. 커밋 메시지
- 의도 중심, `<타입>: <요약>` 포맷
- 예: `✨Feat: 로그인 폼 UI 구현`, `🐛Fix: 결제 실패 오류 수정`
- 패키지 설치 시 설치한 패키지와 목적 명시

### 3. Pull Request
- 한 PR의 코드 라인 수(LoC)는 **최대 500줄 이내**
- PR 전 로컬에서 자체 테스트/검토 완료
- PR 템플릿 서식 준수

### 4. `.gitignore` 확인
로그(`*.log`), 빌드 아티팩트, `.DS_Store`, `.idea/`, `node_modules/` 등은 커밋 금지.

### 5. 민감정보 업로드 금지
`.env`, API 키, 액세스 토큰, DB 비밀번호, 개인정보 데이터 파일은 **절대 커밋 금지**.
