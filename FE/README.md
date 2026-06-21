# Polaryx Frontend

Next.js 15 App Router, React 19, TypeScript, Tailwind CSS, Radix UI, Zustand 기반 frontend 앱입니다.

## Local Development

Node.js 20.19+를 사용합니다.

```bash
npm install
npm run dev
```

## Quality Checks

PR 전 아래 명령을 로컬에서 확인합니다.

```bash
npm run lint
npm run build
npm run test
```

CI는 `npm ci` 후 lint, build, test를 각각 별도 gate로 실행합니다. Test suite는 Vitest + React Testing Library + jsdom을 사용하며 network, Next router, OAuth callback, browser storage는 mock 처리합니다.
