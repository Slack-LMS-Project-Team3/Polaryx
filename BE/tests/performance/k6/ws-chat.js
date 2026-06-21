import exec from "k6/execution";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";
import ws from "k6/ws";

const usersFile = __ENV.USERS_FILE || "../fixtures/users.example.json";
const fixture = JSON.parse(open(usersFile));
const workspaceId = __ENV.WORKSPACE_ID || fixture.workspace_id || 1;
const tabId = __ENV.TAB_ID || fixture.tab_id || 1;
const wsBaseUrl = __ENV.WS_BASE_URL || "ws://localhost:8000/api/ws";
const sendEverySeconds = Number(__ENV.SEND_EVERY_SECONDS || "5");
const vus = Number(__ENV.VUS || "10");
const duration = __ENV.DURATION || "1m";
const stagesSpec = __ENV.STAGES || "";
const senderRatio = __ENV.SENDER_RATIO === undefined ? null : Number(__ENV.SENDER_RATIO);
const senders = __ENV.SENDERS === undefined ? 1 : Number(__ENV.SENDERS);
const gracefulStop = __ENV.GRACEFUL_STOP || "30s";
const deliveryP95ThresholdMs = Number(__ENV.WS_DELIVERY_P95_THRESHOLD_MS || "1000");

function parseDurationSeconds(value) {
  const match = String(value).match(/^(\d+(?:\.\d+)?)(ms|s|m|h)$/);
  if (!match) {
    return 60;
  }
  const amount = Number(match[1]);
  const unit = match[2];
  if (unit === "ms") return amount / 1000;
  if (unit === "s") return amount;
  if (unit === "m") return amount * 60;
  return amount * 60 * 60;
}

const holdSeconds = Number(__ENV.HOLD_SECONDS || Math.max(1, parseDurationSeconds(duration) - 1));
const minHoldSeconds = Number(__ENV.MIN_HOLD_SECONDS || Math.max(1, holdSeconds - 1));

function parseStages(value) {
  if (!value) {
    return null;
  }

  return value.split(",").map((stage) => {
    const [durationValue, targetValue] = stage.trim().split(":");
    if (!durationValue || targetValue === undefined) {
      throw new Error("STAGES must use duration:target entries, for example 2m:100,5m:100,2m:300");
    }
    return {
      duration: durationValue,
      target: Number(targetValue),
    };
  });
}

const stages = parseStages(stagesSpec);
const maxPlannedVus = stages ? Math.max(...stages.map((stage) => stage.target)) : vus;
const plannedSenders = Math.max(0, senderRatio === null ? senders : Math.ceil(maxPlannedVus * senderRatio));
const thresholds = {
  ws_connect_success: ["rate>0.99"],
  ws_maintain_success: ["rate>0.99"],
  ws_errors: ["count==0"],
};

if (plannedSenders > 0) {
  thresholds.ws_delivery_ms = [`p(95)<${deliveryP95ThresholdMs}`];
}

export const options = {
  scenarios: {
    ws_chat: {
      executor: stages ? "ramping-vus" : "constant-vus",
      ...(stages
        ? { stages, gracefulStop }
        : {
            vus,
            duration,
            gracefulStop,
          }),
    },
  },
  thresholds,
};

export const wsConnectSuccess = new Rate("ws_connect_success");
export const wsMaintainSuccess = new Rate("ws_maintain_success");
export const wsMessagesReceived = new Counter("ws_messages_received");
export const wsSendCount = new Counter("ws_send_count");
export const wsErrors = new Counter("ws_errors");
export const wsCloseEvents = new Counter("ws_close_events");
export const wsDeliveryMs = new Trend("ws_delivery_ms", true);
export const wsSessionDurationMs = new Trend("ws_session_duration_ms", true);

function pickUser() {
  const users = fixture.users || [];
  if (users.length === 0) {
    throw new Error(`${usersFile} must contain at least one user`);
  }
  return users[(exec.vu.idInTest - 1) % users.length];
}

function buildUrl() {
  return `${wsBaseUrl}/${workspaceId}/${tabId}`;
}

function parsePerfPayload(message) {
  try {
    const payload = JSON.parse(message);
    if (typeof payload.content !== "string") {
      return null;
    }
    return JSON.parse(payload.content);
  } catch (_) {
    return null;
  }
}

export default function () {
  const user = pickUser();
  const url = buildUrl();
  const headers = {};

  if (__ENV.WS_AUTH_TOKEN) {
    headers.Authorization = `Bearer ${__ENV.WS_AUTH_TOKEN}`;
  } else if (user.access_token) {
    headers.Authorization = `Bearer ${user.access_token}`;
  }

  const response = ws.connect(url, { headers }, (socket) => {
    let openedAtMs = 0;
    let hadError = false;
    let sequence = 0;
    const senderEnabled = exec.vu.idInTest <= plannedSenders;

    socket.on("open", () => {
      openedAtMs = Date.now();
      wsConnectSuccess.add(true);

      if (!senderEnabled) {
        return;
      }

      socket.setInterval(() => {
        const sentAtMs = Date.now();
        const perfPayload = {
          perf_id: `${sentAtMs}-${exec.vu.idInTest}-${sequence}`,
          sent_at_ms: sentAtMs,
          vu: exec.vu.idInTest,
          sequence,
        };
        socket.send(
          JSON.stringify({
            type: "send",
            sender_id: user.user_id,
            content: JSON.stringify(perfPayload),
            file_url: null,
          }),
        );
        wsSendCount.add(1);
        sequence += 1;
      }, sendEverySeconds * 1000);
    });

    socket.on("message", (message) => {
      wsMessagesReceived.add(1);
      const perfPayload = parsePerfPayload(message);
      if (perfPayload && perfPayload.sent_at_ms) {
        wsDeliveryMs.add(Date.now() - perfPayload.sent_at_ms);
      }
    });

    socket.on("error", () => {
      hadError = true;
      wsErrors.add(1);
      wsMaintainSuccess.add(false);
    });

    socket.on("close", (event) => {
      const sessionMs = openedAtMs ? Date.now() - openedAtMs : 0;
      const heldLongEnough = sessionMs >= minHoldSeconds * 1000;
      wsCloseEvents.add(1, { code: String(event && event.code ? event.code : "unknown") });
      wsSessionDurationMs.add(sessionMs);
      wsMaintainSuccess.add(openedAtMs > 0 && heldLongEnough && !hadError);
    });

    socket.setTimeout(() => socket.close(), holdSeconds * 1000);
  });

  check(response, {
    "websocket upgrade status is 101": (res) => res && res.status === 101,
  });
  if (!response || response.status !== 101) {
    wsConnectSuccess.add(false);
    wsMaintainSuccess.add(false);
  }

  sleep(1);
}
