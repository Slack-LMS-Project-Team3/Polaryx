# 📁 파일 업로드 가이드라인

이 레포지토리에 파일을 업로드할 때는 아래 규칙을 반드시 지켜주세요.  
모두가 협업하기 좋은 환경을 만들기 위함입니다 🙏

---
## 0. Reset / Rebase 금지!!!!!!!!!(진짜 중요함!! 안유진, 이재웅과 면담하기 싫음 무조건 지켜라)

## 1. 📂 Branch 생성 규칙!

- 🔒 **절대 `main` 브랜치에 직접 `push`하지 마세요!**
- ✅ `main` 브랜치는 항상 배포 가능한 상태를 유지합니다.
- ⚙️ 모든 기능 개발은 개별 브랜치에서 진행 후 Pull Request로 병합합니다.
- 🔧 브랜치 네이밍 규칙: <기능명> 

- ✅ 예시:
- `login-form`

---

## 2️⃣ 커밋 메시지 작성 규칙

- 커밋 메시지는 **의도 중심으로 명확하게 작성**해주세요.
- 기본 포맷: `<타입>: <무엇을 변경했는지 요약>`
- 패키지 설치 시: 설치한 패키지와 목적을 적어주세요

- ✅ 예시:
  `✨Feat: 로그인 폼 UI 구현`  
  , `🐛Fix: 결제 실패 오류 수정`


### 🔖Commit Message Editor 활용

**설치 및 세팅**
- VS Code의 extension에서 Commit Message Edetior 설치
- Source Control 패널에서 Commit Message 입력창 우측 상단에 연필 모양 버튼 선택
- Commit Message Editor 창 우측 상단의 톱니바퀴 모양 버튼 선택
- Import 버튼 선택 후 'Commit_message_convention.json' 파일 선택 (Slack에 있음)
- 우측 상단에 Save 버튼 선택 
  
**사용법**
- git add 후 Source Control 패널로 이동
- Commit Message 입력창 우측 상단에 연필 모양 버튼 선택
- Edit as text 탭에서 Load tempate 버튼 선택
- Commit type 복사 후, Edit as form 탭으로 이동
- 각 입력 필드에 맞춰 작성 (type은 복사한 내용을 붙여넣기 / (타입 설명) 삭제)
- 하단의 Save 버튼 선택
- Source Control 패널의 Commit Message 입력 창에 입력된 내용 확인
- Commit 버튼 선택

---

## 3️⃣ Pull Request 작성 규칙

- 총 코드 라인 수(LoC, Line of Codes)가 **최대 500줄을 넘기지 않도록**!!
- PR 요청 전, 반드시 **로컬에서 자체 테스트 및 검토**를 완료
- PR 템플릿 서식 맞춰서 PR 메세지 작성하기

---

## 4️⃣ 📦 .gitignore 확인 필수

- 다음과 같은 파일은 절대 커밋하지 마세요:
- 로그 파일 (`*.log`)
- 캐시, 빌드 아티팩트
- `.DS_Store`, `.idea/`, `node_modules/` 등 IDE 설정 파일

---

## 5️⃣ 🔐 민감정보 업로드 금지

- ❌ 절대 업로드하지 말아야 할 항목:
- `.env`
- API 키, 액세스 토큰, DB 비밀번호
- 개인정보가 포함된 데이터 파일

---
