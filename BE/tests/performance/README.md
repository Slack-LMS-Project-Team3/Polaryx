# Polaryx Performance Tests

FastAPI 실시간 경로를 실제로 측정하기 위한 로컬 성능 테스트 스캐폴드입니다.

- WebSocket chat: k6
- Polling messages: Locust
- SSE notifications: Locust

## 1. 서버 준비

로컬 백엔드를 먼저 실행합니다. Docker 기준 기본 API 주소는 `http://localhost:8000`입니다.

```bash
docker compose -f docker-compose.backend.local.yml up -d --build
```

이 명령은 루트 `.env` 파일을 요구합니다. 없으면 먼저 템플릿을 복사한 뒤 실제 로컬/개발 값을 채우세요.

```bash
cp env.template .env
```

`SECRET_KEY`, MySQL, Redis 값은 성능 테스트에서 바로 사용됩니다. OAuth/AWS/VAPID는 앱 설정 검증 때문에 필요하지만, 메시지 polling/WebSocket/SSE 측정만 할 때는 실제 외부 API를 호출하지 않으면 placeholder로 둘 수 있습니다.

Docker 컨테이너에서 호스트 머신의 MySQL/Redis를 바라보게 하려면 `127.0.0.1` 대신 `host.docker.internal`을 사용하세요.

```dotenv
RDB_HOST=host.docker.internal
REDIS_HOST=host.docker.internal
NOSQL_HOST=host.docker.internal
NOSQL_URL=mongodb://host.docker.internal:27017
```

서버가 Polaryx 백엔드인지 먼저 확인합니다.

```bash
curl http://localhost:8000/api/health
```

정상 응답 예시는 다음과 같습니다.

```json
{"status":"healthy","message":"Service is running"}
```

다른 응답이 나오거나 WebSocket이 계속 403이면, 8000 포트를 다른 컨테이너/앱이 점유하고 있을 수 있습니다.

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

예를 들어 다른 컨테이너가 `0.0.0.0:8000->8000/tcp`를 잡고 있으면 먼저 중지하거나 compose 포트를 바꿔야 합니다.

현재 백엔드 Dockerfile은 Uvicorn `--workers 2`로 실행합니다. WebSocket/SSE 안정성 비교를 하려면 같은 조건에서 `workers=1`과 `workers=2`를 각각 따로 측정하세요.

## 2. 테스트 유저 토큰 생성

SSE와 polling API는 `Authorization: Bearer` 토큰이 필요합니다. `BE/.env`의 `SECRET_KEY`와 같은 값으로 로컬 fixture를 생성합니다.

```bash
cd BE
python3 -m venv .venv
source .venv/bin/activate
pip install -r tests/performance/requirements.txt

export SECRET_KEY="$(grep '^SECRET_KEY=' .env | cut -d= -f2-)"
python tests/performance/scripts/generate_tokens.py --force
```

생성되는 `tests/performance/fixtures/users.local.json`은 git에 올라가지 않도록 ignore 되어 있습니다.

## 3. WebSocket 측정

먼저 낮은 부하로 handshake와 broadcast가 정상인지 확인합니다.

```bash
cd BE/tests/performance/k6
k6 run \
  -e WS_BASE_URL=ws://localhost:8000/api/ws \
  -e USERS_FILE=../fixtures/users.local.json \
  -e VUS=10 \
  -e SENDERS=1 \
  -e SEND_EVERY_SECONDS=5 \
  -e DURATION=1m \
  ws-chat.js
```

`ws-chat.js`는 두 가지 WebSocket capacity 시나리오를 지원합니다.

- `VUS`: 고정 동시 접속자 수
- `STAGES`: `duration:target` 형식의 단계 상승 계획. 예: `2m:100,5m:100,2m:300`. 연결 churn/ramp 확인용입니다.
- `SENDERS`: 메시지를 보내는 VU 수. `0`이면 연결 유지 테스트만 수행합니다.
- `SENDER_RATIO`: 전체 계획 VU 대비 송신자 비율. 예: `0.05`는 5% 송신자입니다.
- `SEND_EVERY_SECONDS`: 송신자 1명당 메시지 전송 주기입니다.
- `HOLD_SECONDS`: 각 WebSocket session 유지 시간입니다. 기본값은 `DURATION - 1초`입니다.
- `MIN_HOLD_SECONDS`: 이 시간 이상 유지되고 socket error가 없어야 유지 성공으로 집계합니다.
- `--summary-export`: k6 요약 JSON을 저장하는 옵션입니다. 예: `--summary-export ../results/ws-hold-100.json`

주요 k6 지표:

- `ws_connect_success`: WebSocket upgrade 성공률. 목표는 `>= 99%`입니다.
- `ws_maintain_success`: 연결 유지 성공률. 목표는 `>= 99%`입니다.
- `ws_errors`: socket error 수. 목표는 `0`입니다.
- `ws_session_duration_ms`: 실제 연결 유지 시간입니다.
- `ws_messages_received`: broadcast 수신량입니다.
- `ws_send_count`: 송신 메시지 수입니다.
- `ws_delivery_ms`: 테스트 payload가 broadcast로 돌아오기까지의 지연 시간입니다.

### 3-1. 최대 유지 연결 수 테스트

채팅 전송 없이 연결을 유지하면서 `100 -> 300 -> 500 -> 1000 -> 2000`처럼 목표별로 올립니다. 최대 유지 연결 수는 각 목표를 독립 실행하는 편이 가장 해석하기 쉽습니다.

```bash
k6 run \
  --summary-export ../results/ws-hold-100.json \
  -e USERS_FILE=../fixtures/users.local.json \
  -e WS_BASE_URL=ws://localhost:8000/api/ws \
  -e VUS=100 \
  -e SENDERS=0 \
  -e DURATION=10m \
  ws-chat.js
```

같은 명령에서 `VUS`와 `SUMMARY_FILE`만 바꿔 `300`, `500`, `1000`, `2000`을 반복합니다.

```bash
k6 run \
  --summary-export ../results/ws-hold-500.json \
  -e USERS_FILE=../fixtures/users.local.json \
  -e WS_BASE_URL=ws://localhost:8000/api/ws \
  -e VUS=500 \
  -e SENDERS=0 \
  -e DURATION=10m \
  ws-chat.js
```

연결 생성/종료가 섞인 ramp 자체를 보고 싶을 때만 `STAGES`를 별도 사용합니다.

```bash
k6 run \
  --summary-export ../results/ws-hold-ramp.json \
  -e USERS_FILE=../fixtures/users.local.json \
  -e WS_BASE_URL=ws://localhost:8000/api/ws \
  -e STAGES=2m:100,5m:100,2m:300,5m:300,2m:500,5m:500 \
  -e SENDERS=0 \
  ws-chat.js
```

이 시나리오의 판정 기준:

- WebSocket upgrade 성공률 `>= 99%`
- 연결 유지 성공률 `>= 99%`
- `ws_errors == 0`
- 서버 CPU가 장시간 포화되지 않을 것
- 서버 RSS memory가 계속 증가하지 않을 것
- file descriptor 수가 연결 수 증가 이후 안정화될 것
- Redis/MySQL 로그에 반복 에러가 없을 것

### 3-2. 연결 유지 상태에서 채팅 빈도 테스트

접속자 수를 고정하고 송신자 비율과 전송 주기를 바꿉니다. 같은 tab에 broadcast되므로 서버 출력량은 대략 `송신자 수 * 초당 송신 횟수 * 접속자 수`입니다. 예를 들어 `500명 접속`, `50명 송신`, `1초마다 전송`이면 서버는 초당 약 `25,000`개 WebSocket frame 전송을 시도합니다.

100명 접속, 5% 송신자, 5초 주기:

```bash
k6 run \
  --summary-export ../results/ws-chat-100u-5pct-5s.json \
  -e USERS_FILE=../fixtures/users.local.json \
  -e WS_BASE_URL=ws://localhost:8000/api/ws \
  -e VUS=100 \
  -e SENDER_RATIO=0.05 \
  -e SEND_EVERY_SECONDS=5 \
  -e DURATION=10m \
  ws-chat.js
```

500명 접속, 10% 송신자, 1초 주기:

```bash
k6 run \
  --summary-export ../results/ws-chat-500u-10pct-1s.json \
  -e USERS_FILE=../fixtures/users.local.json \
  -e WS_BASE_URL=ws://localhost:8000/api/ws \
  -e VUS=500 \
  -e SENDER_RATIO=0.10 \
  -e SEND_EVERY_SECONDS=1 \
  -e DURATION=10m \
  ws-chat.js
```

권장 매트릭스:

| 접속자 | 송신자 비율 | 전송 주기 |
| --- | --- | --- |
| 100 | 1%, 5%, 10% | 10s, 5s, 2s, 1s |
| 300 | 1%, 5%, 10% | 10s, 5s, 2s, 1s |
| 500 | 1%, 5%, 10% | 10s, 5s, 2s, 1s |
| 1000 | 1%, 5%, 10% | 10s, 5s, 2s, 1s |

필요할 때만 `SENDER_RATIO=1`로 100% 송신자 테스트를 돌립니다. 이 경우 broadcast fan-out이 매우 커지므로 낮은 접속자 수부터 시작하세요.

서버 관측은 k6 실행 중 별도 터미널에서 같이 기록합니다.

```bash
docker stats
docker compose -f docker-compose.backend.local.yml logs -f backend
docker compose -f docker-compose.backend.local.yml exec backend sh -lc 'for p in $(pgrep -f "uvicorn|python"); do echo "pid=$p fd=$(ls /proc/$p/fd | wc -l)"; grep VmRSS /proc/$p/status; done'
```

Redis/MySQL이 로컬에서 떠 있다면 각각의 에러 로그와 연결 수, slow query도 같은 시간대에 확인합니다. `2000` WebSocket 이상은 k6를 같은 노트북에서 돌릴 때 부하 발생기 한계가 먼저 올 수 있으므로 가능하면 서버와 부하 발생기를 분리해서 측정하세요.

## 4. Polling 측정

```bash
cd BE
locust \
  -f tests/performance/locust/polling_sse.py \
  --host http://localhost:8000 \
  --users 50 \
  --spawn-rate 5 \
  --run-time 5m \
  --headless \
  --only-summary \
  PollingUser
```

Polling 부하는 `POLL_MIN_WAIT`, `POLL_MAX_WAIT`로 조정합니다.

```bash
POLL_MIN_WAIT=1 POLL_MAX_WAIT=1 locust ... PollingUser
```

## 5. SSE 측정

SSE listener만 먼저 연결 안정성을 봅니다.

```bash
cd BE
locust \
  -f tests/performance/locust/polling_sse.py \
  --host http://localhost:8000 \
  --users 50 \
  --spawn-rate 5 \
  --run-time 5m \
  --headless \
  --only-summary \
  SseListenerUser
```

서버의 테스트용 POST endpoint로 SSE 이벤트도 같이 발행하려면 publisher를 추가합니다.

```bash
ENABLE_SSE_PUBLISH=true locust \
  -f tests/performance/locust/polling_sse.py \
  --host http://localhost:8000 \
  --users 60 \
  --spawn-rate 5 \
  --run-time 5m \
  --headless \
  --only-summary \
  SseListenerUser SsePublisherUser
```

## 6. 성능 매트릭스 실행

반복 실행은 `scripts/run_matrix.py`로 관리합니다. 기본 매트릭스는 `100 -> 300 -> 500` users/VU부터 시작하며, 결과는 모두 `tests/performance/results/*.json`으로 저장됩니다.

먼저 실제 실행 없이 명령만 확인합니다.

```bash
cd BE
python tests/performance/scripts/run_matrix.py --dry-run
```

기본 실행은 WebSocket 유지 연결, polling, SSE listener를 각각 `100`, `300`, `500` 동시 사용자로 측정합니다.

```bash
python tests/performance/scripts/run_matrix.py \
  --host http://localhost:8000 \
  --ws-base-url ws://localhost:8000/api/ws \
  --users-file tests/performance/fixtures/users.local.json
```

WebSocket 채팅 fan-out 매트릭스까지 포함하려면 `ws-chat`을 명시합니다. 기본 조합은 `1%`, `5%`, `10%` 송신자와 `10s`, `5s`, `2s`, `1s` 전송 주기입니다.

```bash
python tests/performance/scripts/run_matrix.py \
  --scenarios ws-hold,ws-chat,polling,sse \
  --vus 100,300,500 \
  --ws-duration 10m \
  --locust-run-time 5m
```

서버/부하 발생기 여유가 확인되면 같은 스크립트에서 VU만 확장합니다.

```bash
python tests/performance/scripts/run_matrix.py \
  --scenarios ws-hold,polling,sse \
  --vus 100,300,500,1000,2000 \
  --keep-going
```

주요 옵션:

- `--run-id`: 결과 파일 prefix입니다. 지정하지 않으면 UTC timestamp를 사용합니다.
- `--runtime-label`: 결과 metadata에 남길 런타임/worker label입니다. 예: `workers=1`, `workers=2`
- `--scenarios`: `ws-hold`, `ws-chat`, `polling`, `sse` 중 쉼표로 선택합니다.
- `--vus`: 동시 접속자/사용자 매트릭스입니다. 기본값은 `100,300,500`입니다.
- `--keep-going`: 중간 시나리오가 실패해도 다음 매트릭스를 계속 실행합니다.
- `--spawn-rate`: Locust 사용자 생성 속도입니다. 기본값은 `25` users/sec입니다.
- `--chat-ratios`, `--chat-intervals`: `ws-chat` 조합을 줄이거나 확장합니다.
- `--observability-url`: 각 시나리오 전/후에 보호된 서버 snapshot을 저장할 URL입니다. 예: `http://localhost:8000/api/observability/realtime`
- `--observability-token`: observability snapshot 호출용 bearer token입니다. 생략하면 `users.local.json`의 첫 번째 `access_token`을 사용합니다.

Locust 결과는 `--json` 출력에 실행 metadata를 감싼 형태로 저장합니다. k6 결과는 `--summary-export` 원본 JSON의 top-level `metrics`를 보존하면서 실행 metadata를 추가합니다. `results/` 안의 산출물은 git에 올라가지 않습니다.

서버 observability를 함께 수집하려면 다음처럼 실행합니다. 각 결과 JSON metadata에는 before/after snapshot sidecar 경로가 들어가고, sidecar 파일은 같은 `results/` 디렉터리에 `*.observability-before.json`, `*.observability-after.json`으로 저장됩니다.

```bash
python tests/performance/scripts/run_matrix.py \
  --scenarios ws-hold,polling,sse \
  --vus 100,300,500 \
  --host http://localhost:8000 \
  --ws-base-url ws://localhost:8000/api/ws \
  --users-file tests/performance/fixtures/users.local.json \
  --observability-url http://localhost:8000/api/observability/realtime
```

## 7. 요약 리포트 생성

매트릭스 실행 후 JSON 결과를 Markdown 표로 합칩니다.

```bash
cd BE
python tests/performance/scripts/summarize_results.py
```

기본 출력은 `tests/performance/results/summary.md`입니다. 경로를 바꾸려면 다음처럼 실행합니다.

```bash
python tests/performance/scripts/summarize_results.py \
  --results-dir tests/performance/results \
  --output tests/performance/results/summary-$(date -u +%Y%m%dT%H%M%SZ).md
```

특정 run id 또는 runtime label만 분리하려면 filter를 사용합니다.

```bash
python tests/performance/scripts/summarize_results.py \
  --results-dir tests/performance/results \
  --run-id workers1-20260618T090000Z \
  --output tests/performance/results/summary-workers1-20260618T090000Z.md

python tests/performance/scripts/summarize_results.py \
  --results-dir tests/performance/results \
  --runtime-label workers=2 \
  --output tests/performance/results/summary-workers2-latest.md
```

## 8. workers=1 vs workers=2 비교 절차

`tests/performance/fixtures/users.local.json`에는 생성된 JWT가 들어 있으므로 git에 올리지 않습니다. 실행 전 token fixture가 최신인지 확인하세요.

workers=1은 Dockerfile을 수정하지 않고 compose one-off command로 띄웁니다. 이 명령은 foreground에서 실행되므로 별도 터미널을 사용합니다.

```bash
docker compose -f docker-compose.backend.local.yml down
docker compose -f docker-compose.backend.local.yml build backend
docker compose -f docker-compose.backend.local.yml run --rm --service-ports backend \
  uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --ws-ping-interval 90 \
    --workers 1
```

다른 터미널에서 같은 baseline matrix를 실행하고, run id와 runtime label을 함께 남깁니다.

```bash
cd BE
RUN_ID="workers1-$(date -u +%Y%m%dT%H%M%SZ)"
python tests/performance/scripts/run_matrix.py \
  --scenarios ws-hold,polling,sse \
  --vus 100,300,500 \
  --host http://localhost:8000 \
  --ws-base-url ws://localhost:8000/api/ws \
  --users-file tests/performance/fixtures/users.local.json \
  --observability-url http://localhost:8000/api/observability/realtime \
  --run-id "$RUN_ID" \
  --runtime-label workers=1

python tests/performance/scripts/summarize_results.py \
  --results-dir tests/performance/results \
  --run-id "$RUN_ID" \
  --output "tests/performance/results/summary-${RUN_ID}.md"
```

workers=2는 현재 Dockerfile의 기본 runtime-like baseline입니다.

```bash
docker compose -f docker-compose.backend.local.yml down
docker compose -f docker-compose.backend.local.yml up -d --build backend
```

같은 smoke 또는 baseline matrix를 동일한 옵션으로 반복합니다.

```bash
cd BE
RUN_ID="workers2-$(date -u +%Y%m%dT%H%M%SZ)"
python tests/performance/scripts/run_matrix.py \
  --scenarios ws-hold,polling,sse \
  --vus 100,300,500 \
  --host http://localhost:8000 \
  --ws-base-url ws://localhost:8000/api/ws \
  --users-file tests/performance/fixtures/users.local.json \
  --observability-url http://localhost:8000/api/observability/realtime \
  --run-id "$RUN_ID" \
  --runtime-label workers=2

python tests/performance/scripts/summarize_results.py \
  --results-dir tests/performance/results \
  --run-id "$RUN_ID" \
  --output "tests/performance/results/summary-${RUN_ID}.md"
```

WebSocket은 Redis Pub/Sub fan-out, SSE는 process-local subscriber map의 영향을 받으므로 workers=1과 workers=2 결과를 평균으로 합치지 말고 별도 summary로 비교하세요. Observability snapshot도 process-local입니다. workers=2에서 한 번의 `/api/observability/realtime` 응답은 해당 요청을 처리한 worker 하나의 상태이므로 cluster-wide total로 해석하지 마세요.

## 9. 권장 측정 순서

1. WebSocket 10 VU smoke
2. Polling 10 users smoke
3. SSE 10 users smoke
4. `run_matrix.py --dry-run`으로 명령과 파일명을 확인
5. WebSocket/Polling/SSE `100 -> 300 -> 500`
6. WebSocket chat fan-out `100 -> 300 -> 500`
7. 서버 여유가 있으면 `1000 -> 2000`으로 확장
8. 같은 시나리오를 `workers=1`과 `workers=2`에서 반복
9. `summarize_results.py`로 Markdown 요약 생성

비교할 때는 p50/p95/p99 지연 시간, 오류율, 서버 CPU/메모리, DB 커넥션, Redis 상태를 같이 기록하세요.
