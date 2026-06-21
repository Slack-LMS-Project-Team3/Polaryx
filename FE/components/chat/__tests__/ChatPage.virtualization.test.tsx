import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getMessages } from "@/apis/messageApi";
import { useMessageStore } from "@/store/messageStore";
import { ChatPage } from "../ChatPage";

vi.mock("@/apis/messageApi", () => ({
  getMessages: vi.fn(),
}));

vi.mock("../ChatProfile", () => ({
  ChatProfile: ({
    msgId,
    content,
    showProfile,
    isEditMode,
    onStartEdit,
    clapCnt,
  }: {
    msgId: number | string;
    content: string;
    showProfile: boolean;
    isEditMode: boolean;
    onStartEdit: () => void;
    clapCnt: number;
  }) => (
    <div
      data-testid="chat-profile"
      data-msg-id={String(msgId)}
      data-show-profile={String(showProfile)}
    >
      {content}
      <span data-testid={`edit-state-${msgId}`}>{String(isEditMode)}</span>
      <span data-testid={`clap-count-${msgId}`}>{clapCnt}</span>
      <button data-testid={`edit-${msgId}`} onClick={onStartEdit}>
        edit
      </button>
    </div>
  ),
}));

vi.mock("../ShowDate", () => ({
  ShowDate: ({ timestamp }: { timestamp: number }) => (
    <div data-testid="chat-date">{timestamp}</div>
  ),
}));

vi.mock("../../sse/SSEListener", () => ({
  SSEListener: () => <div data-testid="sse-listener" />,
}));

vi.mock("../../ws/RealtimeWebSocketClient", () => ({
  RealtimeWebSocketClient: () => <div data-testid="realtime-client" />,
}));

const getMessagesMock = vi.mocked(getMessages);
let scrollToMock: ReturnType<typeof vi.fn>;
const originalScrollTo = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollTo",
);
const originalClientHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "clientHeight",
);
const originalScrollHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollHeight",
);

function restorePrototypeDescriptor(
  key: "scrollTo" | "clientHeight" | "scrollHeight",
  descriptor: PropertyDescriptor | undefined,
) {
  if (descriptor) {
    Object.defineProperty(HTMLElement.prototype, key, descriptor);
  } else {
    delete (HTMLElement.prototype as Record<string, unknown>)[key];
  }
}

function apiMessage(id: number, overrides: Record<string, unknown> = {}) {
  return {
    sender_id: `user-${id % 3}`,
    msg_id: id,
    nickname: `User ${id % 3}`,
    content: `message ${id}`,
    image: "/user_default.png",
    created_at: `2026-06-21T10:${String(id % 60).padStart(2, "0")}:00+09:00`,
    is_updated: 0,
    file_url: null,
    e_check_cnt: 0,
    e_clap_cnt: 0,
    e_like_cnt: 0,
    e_sparkle_cnt: 0,
    e_pray_cnt: 0,
    my_toggle: {
      check: false,
      pray: false,
      sparkle: false,
      clap: false,
      like: false,
    },
    ...overrides,
  };
}

function setScrollGeometry(element: HTMLElement, geometry = {}) {
  const values = {
    clientHeight: 640,
    scrollHeight: 6400,
    scrollTop: 0,
    ...geometry,
  };

  Object.defineProperties(element, {
    clientHeight: { configurable: true, value: values.clientHeight },
    scrollHeight: { configurable: true, value: values.scrollHeight },
    scrollTop: { configurable: true, writable: true, value: values.scrollTop },
  });
}

describe("ChatPage virtualization", () => {
  beforeEach(() => {
    getMessagesMock.mockReset();
    useMessageStore.setState({
      messages: [],
      unreadCounts: {},
      invitedTabs: [],
      pendingEmojiUpdates: [],
      inFlightEmojiUpdates: [],
      fileUrl: null,
      editMessage: { msgId: 0, content: "" },
      sendFlag: false,
      editMsgFlag: false,
      sendEmojiFlag: false,
      sendEditFlag: false,
    });

    class ResizeObserverMock {
      observe() {}
      unobserve() {}
      disconnect() {}
    }

    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    scrollToMock = vi.fn(function (
      this: HTMLElement,
      options?: ScrollToOptions | number,
      y?: number,
    ) {
      const nextTop =
        typeof options === "object"
          ? Number(options.top ?? 0)
          : Number(y ?? options ?? 0);

      Object.defineProperty(this, "scrollTop", {
        configurable: true,
        writable: true,
        value: nextTop,
      });
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollToMock,
    });
    Object.defineProperties(HTMLElement.prototype, {
      clientHeight: {
        configurable: true,
        get() {
          return (this as HTMLElement).dataset.testid ===
            "chat-scroll-container"
            ? 640
            : 72;
        },
      },
      scrollHeight: {
        configurable: true,
        get() {
          return (this as HTMLElement).dataset.testid ===
            "chat-scroll-container"
            ? 6400
            : 72;
        },
      },
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      width: 1024,
      height: 72,
      top: 0,
      left: 0,
      right: 1024,
      bottom: 72,
      toJSON: () => ({}),
    });
  });

  afterEach(() => {
    restorePrototypeDescriptor("scrollTo", originalScrollTo);
    restorePrototypeDescriptor("clientHeight", originalClientHeight);
    restorePrototypeDescriptor("scrollHeight", originalScrollHeight);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each([1000, 5000, 10000])(
    "mounts a bounded number of message rows for a %i-message channel",
    async (messageCount) => {
      getMessagesMock.mockResolvedValueOnce({
        messages: Array.from({ length: messageCount }, (_, index) =>
          apiMessage(index + 1),
        ),
      });

      render(<ChatPage workspaceId="1" tabId="2" />);

      await waitFor(() =>
        expect(useMessageStore.getState().messages).toHaveLength(messageCount),
      );

      await waitFor(() =>
        expect(screen.getAllByTestId("chat-profile").length).toBeGreaterThan(0),
      );

      const mountedRows = screen.getAllByTestId("chat-profile");
      expect(mountedRows.length).toBeGreaterThan(0);
      expect(mountedRows.length).toBeLessThanOrEqual(80);
      expect(mountedRows.length).toBeLessThan(messageCount);
      expect(screen.getAllByTestId("sse-listener")).toHaveLength(1);
      expect(screen.getAllByTestId("realtime-client")).toHaveLength(1);
    },
  );

  it("maps snake_case API fields and fetches older history once at the top", async () => {
    let resolveOlder: (value: { messages: ReturnType<typeof apiMessage>[] }) => void = () => {};
    const olderPage = new Promise<{ messages: ReturnType<typeof apiMessage>[] }>((resolve) => {
      resolveOlder = resolve;
    });

    getMessagesMock
      .mockResolvedValueOnce({
        messages: Array.from({ length: 50 }, (_, index) => apiMessage(index + 51)),
      })
      .mockReturnValueOnce(olderPage);

    render(<ChatPage workspaceId="1" tabId="2" />);

    await waitFor(() => expect(useMessageStore.getState().messages).toHaveLength(50));
    expect(useMessageStore.getState().messages[0]).toMatchObject({
      senderId: "user-0",
      msgId: 51,
      createdAt: "2026-06-21T10:51:00+09:00",
      fileUrl: null,
      checkCnt: 0,
      myToggle: expect.objectContaining({ check: false }),
    });

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    setScrollGeometry(scrollContainer, { scrollTop: 0 });

    fireEvent.scroll(scrollContainer);
    fireEvent.scroll(scrollContainer);

    expect(getMessagesMock).toHaveBeenCalledTimes(2);
    expect(getMessagesMock).toHaveBeenLastCalledWith("1", "2", 51);

    resolveOlder({
      messages: [apiMessage(49), apiMessage(50), apiMessage(51)],
    });

    await waitFor(() => {
      const ids = useMessageStore.getState().messages.map((msg) => msg.msgId);
      expect(ids.slice(0, 4)).toEqual([49, 50, 51, 52]);
      expect(ids.filter((id) => id === 51)).toHaveLength(1);
    });
  });

  it("keeps string temp message ids on visible row actions", async () => {
    getMessagesMock.mockResolvedValueOnce({
      messages: [
        apiMessage(1, {
          msg_id: "temp_abc",
          content: "pending message",
        }),
      ],
    });

    render(<ChatPage workspaceId="1" tabId="2" />);

    const row = await screen.findByText("pending message");
    const profile = row.closest("[data-msg-id]");
    expect(profile).toHaveAttribute("data-msg-id", "temp_abc");

    fireEvent.click(screen.getByTestId("edit-temp_abc"));
    expect(screen.getByTestId("edit-state-temp_abc")).toHaveTextContent("true");
  });

  it("follows appended messages only while the user is near the bottom", async () => {
    getMessagesMock.mockResolvedValueOnce({
      messages: Array.from({ length: 20 }, (_, index) => apiMessage(index + 1)),
    });

    render(<ChatPage workspaceId="1" tabId="2" />);

    await waitFor(() => expect(useMessageStore.getState().messages).toHaveLength(20));
    await waitFor(() => expect(scrollToMock).toHaveBeenCalled());
    scrollToMock.mockClear();

    useMessageStore.getState().appendMessage(apiMessage(21) as any);

    await waitFor(() => expect(scrollToMock).toHaveBeenCalled());
    scrollToMock.mockClear();

    const scrollContainer = screen.getByTestId("chat-scroll-container");
    setScrollGeometry(scrollContainer, { scrollTop: 100, scrollHeight: 6400 });
    fireEvent.scroll(scrollContainer);
    await new Promise((resolve) => setTimeout(resolve, 0));
    scrollToMock.mockClear();

    useMessageStore.getState().appendMessage(apiMessage(22) as any);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(scrollToMock).not.toHaveBeenCalled();
  });

  it("keeps edit mode open for a visible row across store-driven rerenders", async () => {
    getMessagesMock.mockResolvedValueOnce({
      messages: Array.from({ length: 20 }, (_, index) => apiMessage(index + 1)),
    });

    render(<ChatPage workspaceId="1" tabId="2" />);

    await waitFor(() => expect(useMessageStore.getState().messages).toHaveLength(20));
    const editButton = (await screen.findAllByText("edit"))[0];
    const msgId = Number(
      editButton
        .closest("[data-msg-id]")
        ?.getAttribute("data-msg-id"),
    );

    fireEvent.click(editButton);
    expect(screen.getByTestId(`edit-state-${msgId}`)).toHaveTextContent("true");

    useMessageStore.getState().updateEmojiCounts(msgId, {
      checkCnt: 0,
      prayCnt: 0,
      sparkleCnt: 0,
      clapCnt: 3,
      likeCnt: 0,
    });

    await waitFor(() =>
      expect(screen.getByTestId(`clap-count-${msgId}`)).toHaveTextContent("3"),
    );
    expect(screen.getByTestId(`edit-state-${msgId}`)).toHaveTextContent("true");
  });
});
