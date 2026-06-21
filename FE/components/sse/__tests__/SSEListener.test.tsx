import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMessageStore } from "@/store/messageStore";
import { useTabStore } from "@/store/tabStore";

vi.mock("next/navigation", () => ({
  useParams: () => ({ workspaceId: "1", tabId: "2" }),
}));

function createLocalStorageMock() {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
}

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function jsonResponse(payload: unknown = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function createSseFetchMock(streams: Response[]) {
  const pendingStreams = [...streams];
  return vi.fn((input: RequestInfo | URL) => {
    const url = input.toString();
    if (url.includes("/api/sse/notifications/ack")) {
      return Promise.resolve(jsonResponse({ status: "acked" }));
    }
    return Promise.resolve(pendingStreams.shift() ?? streamResponse([]));
  });
}

describe("SSEListener", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_BASE", "http://localhost:8000");
    vi.stubGlobal("localStorage", createLocalStorageMock());
    localStorage.setItem("access_token", "token");
    useMessageStore.setState({
      unreadCounts: {},
      invitedTabs: [],
    });
    useTabStore.setState({ needsRefresh: false });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("ignores ping frames without changing notification state", async () => {
    const fetchMock = createSseFetchMock([streamResponse(["event: ping\ndata: p\n\n"])]);
    vi.stubGlobal("fetch", fetchMock);
    const { SSEListener } = await import("../SSEListener");

    const { unmount } = render(<SSEListener />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(useMessageStore.getState().unreadCounts).toEqual({});
    expect(useMessageStore.getState().invitedTabs).toEqual([]);
    unmount();
  });

  it("parses split frames and increments unread only for other tabs", async () => {
    const fetchMock = createSseFetchMock([
      streamResponse([
        "id: evt-1\nevent: new_message\nd",
        'ata: {"type":"new_message","tab_id":3}\n\n',
        'id: evt-2\nevent: new_message\ndata: {"type":"new_message","tab_id":2}\n\n',
      ]),
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const { SSEListener } = await import("../SSEListener");

    const { unmount } = render(<SSEListener />);

    await waitFor(() => expect(useMessageStore.getState().unreadCounts[3]).toBe(1));
    expect(useMessageStore.getState().unreadCounts[2]).toBeUndefined();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/sse/notifications/ack",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ workspace_id: "1", last_event_id: "evt-2" }),
      }),
    ));
    expect(localStorage.getItem("sse:lastEventId:1")).toBe("evt-2");
    unmount();
  });

  it("adds invited tabs and refreshes tabs for invited_to_tab events", async () => {
    const fetchMock = createSseFetchMock([
      streamResponse([
        'id: evt-3\nevent: invited_to_tab\ndata: {"type":"invited_to_tab","tab_id":"5"}\n\n',
      ]),
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const { SSEListener } = await import("../SSEListener");

    const { unmount } = render(<SSEListener />);

    await waitFor(() => expect(useMessageStore.getState().invitedTabs).toContain(5));
    expect(useTabStore.getState().needsRefresh).toBe(true);
    unmount();
  });

  it("does not run side effects twice for duplicate event ids", async () => {
    const fetchMock = createSseFetchMock([
      streamResponse([
        'id: evt-duplicate\nevent: new_message\ndata: {"type":"new_message","tab_id":3}\n\n',
        'id: evt-duplicate\nevent: new_message\ndata: {"type":"new_message","tab_id":3}\n\n',
      ]),
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const { SSEListener } = await import("../SSEListener");

    const { unmount } = render(<SSEListener />);

    await waitFor(() => expect(useMessageStore.getState().unreadCounts[3]).toBe(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(useMessageStore.getState().unreadCounts[3]).toBe(1);
    unmount();
  });

  it("reconnects after a dropped fetch stream", async () => {
    localStorage.setItem("sse:lastEventId:1", "evt-before");
    const fetchMock = createSseFetchMock([
      streamResponse([]),
      streamResponse([
        'id: evt-4\nevent: new_message\ndata: {"type":"new_message","tab_id":4}\n\n',
      ]),
    ]);
    vi.stubGlobal("fetch", fetchMock);
    const { SSEListener } = await import("../SSEListener");

    const { unmount } = render(<SSEListener reconnectBaseDelayMs={1} />);

    await waitFor(() => expect(useMessageStore.getState().unreadCounts[4]).toBe(1));
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(fetchMock.mock.calls[0][0].toString()).toContain("lastEventId=evt-before");
    unmount();
  });
});
