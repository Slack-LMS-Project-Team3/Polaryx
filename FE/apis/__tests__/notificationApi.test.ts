import { beforeEach, describe, expect, it, vi } from "vitest";

const API_BASE = "https://api.example.test";

const mocks = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
}));

vi.mock("../authApi", () => ({
  fetchWithAuth: mocks.fetchWithAuth,
}));

async function loadNotificationApi() {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_BASE", API_BASE);
  return import("../notificationApi");
}

describe("webPush", () => {
  beforeEach(() => {
    mocks.fetchWithAuth.mockReset();
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("returns queued metadata for accepted async push responses", async () => {
    const { webPush } = await loadNotificationApi();
    mocks.fetchWithAuth.mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "queued",
          job_id: "job-1",
          recipient_count: null,
          recipient_count_status: "deferred",
        }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(webPush("1", "2", "hello")).resolves.toEqual({
      ok: true,
      status: 202,
      queued: true,
      jobId: "job-1",
      recipientCount: null,
      recipientCountStatus: "deferred",
    });

    expect(mocks.fetchWithAuth).toHaveBeenCalledWith(
      `${API_BASE}/api/notifications/1/2`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ type: "new_message", content: "hello" }),
      }),
    );
  });

  it("absorbs null responses from fetchWithAuth", async () => {
    const { webPush } = await loadNotificationApi();
    mocks.fetchWithAuth.mockResolvedValue(null);

    await expect(webPush("1", "2", "hello")).resolves.toEqual({
      ok: false,
      error: "NO_RESPONSE",
    });
  });

  it("absorbs non-2xx responses without throwing", async () => {
    const { webPush } = await loadNotificationApi();
    mocks.fetchWithAuth.mockResolvedValue(new Response("unavailable", { status: 503 }));

    await expect(webPush("1", "2", "hello")).resolves.toEqual({
      ok: false,
      status: 503,
      error: "HTTP_ERROR",
    });
  });

  it("absorbs fetch rejection so fire-and-forget callers do not create unhandled rejections", async () => {
    const { webPush } = await loadNotificationApi();
    mocks.fetchWithAuth.mockRejectedValue(new Error("network down"));

    await expect(webPush("1", "2", "hello")).resolves.toEqual({
      ok: false,
      error: "FETCH_FAILED",
    });
    expect(console.warn).toHaveBeenCalled();
  });
});
