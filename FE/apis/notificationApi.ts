import { fetchWithAuth } from "./authApi";

const BASE = process.env.NEXT_PUBLIC_BASE;

export type WebPushResult = {
  ok: boolean;
  status?: number;
  queued?: boolean;
  jobId?: string;
  recipientCount?: number | null;
  recipientCountStatus?: string;
  error?: string;
};

type WebPushQueuedPayload = {
  status?: unknown;
  job_id?: unknown;
  recipient_count?: unknown;
  recipient_count_status?: unknown;
};

/* sse 알림 보내기  */
export async function alarmSSE(workspaceId: string, tabId: string, type: string ): Promise<any> {
  const res = await fetchWithAuth(`${BASE}/api/sse/notifications/${workspaceId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ 
        type: type,
        tab_id: tabId,
    }),
    },
  );
  if (res == null || !res.ok) throw new Error("SSE 송신 실패");
  return res.json();
}

/* 웹푸시 보내기  */
export async function webPush (workspaceId: string, tabId: string, content: string ): Promise<WebPushResult> {
  try {
    const res = await fetchWithAuth(
      `${BASE}/api/notifications/${workspaceId}/${tabId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          type: "new_message",
          content: content,
        }),
      },
    );

    if (res == null) {
      return { ok: false, error: "NO_RESPONSE" };
    }
    if (!res.ok) {
      return { ok: false, status: res.status, error: "HTTP_ERROR" };
    }

    let payload: WebPushQueuedPayload | null = null;
    try {
      const parsed: unknown = await res.json();
      payload = parsed && typeof parsed === "object" ? parsed as WebPushQueuedPayload : null;
    } catch {
      payload = null;
    }

    return {
      ok: true,
      status: res.status,
      queued: payload?.status === "queued",
      jobId: typeof payload?.job_id === "string" ? payload.job_id : undefined,
      recipientCount:
        typeof payload?.recipient_count === "number" || payload?.recipient_count === null
          ? payload.recipient_count
          : undefined,
      recipientCountStatus:
        typeof payload?.recipient_count_status === "string"
          ? payload.recipient_count_status
          : undefined,
    };
  } catch (error) {
    console.warn("Web Push request failed", error);
    return { ok: false, error: "FETCH_FAILED" };
  }
}
