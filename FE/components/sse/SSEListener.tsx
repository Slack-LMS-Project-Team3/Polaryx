"use client";

const BASE = process.env.NEXT_PUBLIC_BASE;

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useMessageStore } from "@/store/messageStore";
import { useTabStore } from "@/store/tabStore";

interface SSEPayload {
  type: "new_message" | "invited_to_tab"; // 타입 2개임: 새 메시지 | 탭에 초대
  tab_id: number | string; // 메시지를 보낸 탭의 id
  sender_id?: string; // 메시지 보낸 유저의 id
  event_id?: string;
  published_at_ms?: number;
}

interface SSEFrame {
  id: string | null;
  eventType: string | null;
  data: string | null;
}

interface SSEListenerProps {
  reconnectBaseDelayMs?: number;
}

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY_MS = 500;
const RECONNECT_MAX_DELAY_MS = 5000;
const PROCESSED_EVENT_LIMIT = 512;

export function drainSSEFrames(buffer: string): {
  frames: SSEFrame[];
  remainingBuffer: string;
} {
  const frames: SSEFrame[] = [];
  let remainingBuffer = buffer;
  let boundaryIndex = remainingBuffer.indexOf("\n\n");

  while (boundaryIndex >= 0) {
    const rawFrame = remainingBuffer.slice(0, boundaryIndex);
    remainingBuffer = remainingBuffer.slice(boundaryIndex + 2);
    boundaryIndex = remainingBuffer.indexOf("\n\n");

    const frame = parseSSEFrame(rawFrame);
    if (frame.eventType || frame.data) {
      frames.push(frame);
    }
  }

  return { frames, remainingBuffer };
}

function parseSSEFrame(rawFrame: string): SSEFrame {
  let id: string | null = null;
  let eventType: string | null = null;
  const dataLines: string[] = [];

  for (const rawLine of rawFrame.split(/\r?\n/)) {
    if (rawLine.startsWith("id:")) {
      id = rawLine.slice(3).trim();
    } else if (rawLine.startsWith("event:")) {
      eventType = rawLine.slice(6).trim();
    } else if (rawLine.startsWith("data:")) {
      dataLines.push(rawLine.slice(5).trim());
    }
  }

  return {
    id,
    eventType,
    data: dataLines.length > 0 ? dataLines.join("\n") : null,
  };
}

function reconnectDelay(attempt: number, baseDelayMs: number): number {
  return Math.min(RECONNECT_MAX_DELAY_MS, baseDelayMs * 2 ** Math.max(0, attempt - 1));
}

export function SSEListener({ reconnectBaseDelayMs = RECONNECT_BASE_DELAY_MS }: SSEListenerProps = {}) {
  const params = useParams();
  const tabId = params.tabId as string;
  const workspaceId = params.workspaceId as string;
  const incUnread = useMessageStore((s) => s.incrementUnread);
  const addInvitedTab = useMessageStore((s) => s.addInvitedTab);
  const refreshTabs = useTabStore((s) => s.refreshTabs);

  useEffect(() => {
    const accessToken = localStorage.getItem("access_token");
    if (!accessToken) {
      console.warn("No access token available for SSE.");
      return;
    }

    const cursorStorageKey = `sse:lastEventId:${workspaceId}`;
    const controller = new AbortController();
    const processedEventIds: string[] = [];
    const processedEventIdSet = new Set<string>();
    let stopped = false;

    const rememberEventId = (eventId: string) => {
      localStorage.setItem(cursorStorageKey, eventId);
      if (processedEventIdSet.has(eventId)) return;
      processedEventIdSet.add(eventId);
      processedEventIds.push(eventId);
      while (processedEventIds.length > PROCESSED_EVENT_LIMIT) {
        const oldest = processedEventIds.shift();
        if (oldest) processedEventIdSet.delete(oldest);
      }
    };

    const lastStoredEventId = localStorage.getItem(cursorStorageKey);
    if (lastStoredEventId) {
      processedEventIdSet.add(lastStoredEventId);
      processedEventIds.push(lastStoredEventId);
    }

    function handlePayload(payload: SSEPayload) {
      const payloadTabId = Number(payload.tab_id);
      if (Number.isNaN(payloadTabId)) return;

      if (payload.type === 'new_message') {
        console.log("SSE: 새 메세지 도착");
        if (payload.tab_id.toString() !== tabId) {
          incUnread(payloadTabId);
        }
      } else if (payload.type === 'invited_to_tab') {
        console.log("SSE: 새로운 탭 초대");
        addInvitedTab(payloadTabId);
        refreshTabs();
      }
    }

    async function ackEvent(eventId: string) {
      try {
        await fetch(`${BASE}/api/sse/notifications/ack`, {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${accessToken}`,
            "Content-Type": "application/json",
            "Accept": "application/json",
          },
          body: JSON.stringify({
            workspace_id: workspaceId,
            last_event_id: eventId,
          }),
          signal: controller.signal,
        });
      } catch (error) {
        if (!controller.signal.aborted) {
          console.log("SSE: ack 실패", error);
        }
      }
    }

    async function handleFrame(frame: SSEFrame) {
      if (frame.data === 'p' || frame.eventType === 'ping') {
        console.log("SSE: 유지 ping");
        return;
      }
      if (!frame.data) return;

      try {
        const payload: SSEPayload = JSON.parse(frame.data);
        const eventId = frame.id || payload.event_id;
        if (eventId && processedEventIdSet.has(eventId)) {
          return;
        }
        handlePayload(payload);
        if (eventId) {
          rememberEventId(eventId);
          await ackEvent(eventId);
        }
      } catch (e) {
        console.error("SSE data parse error:", e);
      }
    }

    function buildStreamUrl() {
      const url = new URL(`${BASE}/api/sse/notifications`);
      url.searchParams.set("workspaceId", workspaceId);
      const lastEventId = localStorage.getItem(cursorStorageKey);
      if (lastEventId) {
        url.searchParams.set("lastEventId", lastEventId);
      }
      return url.toString();
    }

    async function connectOnce() {
      try {
        const response = await fetch(buildStreamUrl(), {
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Accept': 'text/event-stream',
          },
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        console.log("SSE: 연결");

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        if (!reader) return;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const drained = drainSSEFrames(buffer);
          buffer = drained.remainingBuffer;

          for (const frame of drained.frames) {
            await handleFrame(frame);
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          console.log("SSE: 연결 끊김", error);
          throw error;
        }
      }
    }

    async function connectSSE() {
      for (let attempt = 0; attempt <= MAX_RECONNECT_ATTEMPTS && !stopped; attempt += 1) {
        try {
          await connectOnce();
        } catch {
          // connectOnce already logged the disconnect cause.
        }
        if (stopped || attempt === MAX_RECONNECT_ATTEMPTS) break;
        await new Promise((resolve) => setTimeout(resolve, reconnectDelay(attempt + 1, reconnectBaseDelayMs)));
      }
    }

    void connectSSE();

    return () => {
      stopped = true;
      controller.abort();
    };
  }, [workspaceId, incUnread, refreshTabs, addInvitedTab, tabId, reconnectBaseDelayMs]);

  return null;
}
