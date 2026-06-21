import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMessageStore } from "@/store/messageStore";
import { useProfileStore } from "@/store/profileStore";
import { useTabStore } from "@/store/tabStore";
import { alarmSSE, webPush } from "@/apis/notificationApi";
import { jwtDecode } from "jwt-decode";

vi.mock("@/apis/notificationApi", () => ({
  alarmSSE: vi.fn(),
  webPush: vi.fn(),
}));

vi.mock("jwt-decode", () => ({
  jwtDecode: vi.fn(),
}));

const alarmSSEMock = vi.mocked(alarmSSE);
const webPushMock = vi.mocked(webPush);
const jwtDecodeMock = vi.mocked(jwtDecode);

class MockWebSocket {
  static OPEN = 1;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.OPEN;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  receive(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

class MockBroadcastChannel {
  static posted: object[] = [];

  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(public name: string) {}

  postMessage(payload: object) {
    MockBroadcastChannel.posted.push(payload);
  }

  close() {}
}

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

describe("RealtimeWebSocketClient", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_WS", "ws://localhost:8000");
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("BroadcastChannel", MockBroadcastChannel);
    vi.stubGlobal("localStorage", createLocalStorageMock());
    localStorage.setItem("access_token", "token");
    jwtDecodeMock.mockReturnValue({ user_id: "user-1" });
    alarmSSEMock.mockResolvedValue({});
    webPushMock.mockResolvedValue({});
    MockWebSocket.instances = [];
    MockBroadcastChannel.posted = [];
    useMessageStore.setState({
      message: "",
      sendFlag: false,
      editMsgFlag: false,
      sendEmojiFlag: false,
      sendEditFlag: false,
      messages: [],
      fileUrl: null,
      pendingEmojiUpdates: [],
      inFlightEmojiUpdates: [],
      editTarget: { "": "" },
      editMessage: { msgId: 0, content: "" },
    });
    useTabStore.setState({ needsRefresh: false });
    useProfileStore.setState({ isOpen: false, userId: null, profile: null });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("opens one unified socket and applies typed broadcasts", async () => {
    const { RealtimeWebSocketClient } = await import("../RealtimeWebSocketClient");

    render(<RealtimeWebSocketClient workspaceId="1" tabId="2" />);

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toBe("ws://localhost:8000/api/ws/1/2");

    MockWebSocket.instances[0].receive({
      type: "send",
      file_url: "file.png",
      content: "hello",
      nickname: "QA",
      image: "profile.png",
      created_at: "2026-06-19T10:00:00+09:00",
      message_id: "temp_1",
      sender_id: "user-2",
    });

    expect(useMessageStore.getState().messages[0]).toMatchObject({
      senderId: "user-2",
      msgId: "temp_1",
      fileUrl: "file.png",
      content: "hello",
      checkCnt: 0,
      clapCnt: 0,
      likeCnt: 0,
      prayCnt: 0,
      sparkleCnt: 0,
    });

    useMessageStore.setState({
      messages: [
        {
          tabId: 2,
          senderId: "user-2",
          msgId: 303,
          nickname: "Old",
          image: "old.png",
          content: "message",
          createdAt: "2026-06-19T10:00:00+09:00",
          fileUrl: null,
          isUpdated: 0,
          checkCnt: 0,
          clapCnt: 0,
          likeCnt: 0,
          prayCnt: 0,
          sparkleCnt: 0,
          myToggle: { check: false, clap: false, like: false, pray: false, sparkle: false },
        },
      ],
      inFlightEmojiUpdates: [{ msgId: 303, emojiType: "clap", emojiAction: "like" }],
    });

    MockWebSocket.instances[0].receive({
      type: "emoji_update",
      messageId: 303,
      checkCnt: 1,
      clapCnt: 2,
      likeCnt: 3,
      prayCnt: 4,
      sparkleCnt: 5,
    });

    expect(useMessageStore.getState().messages[0]).toMatchObject({
      checkCnt: 1,
      clapCnt: 2,
      likeCnt: 3,
      prayCnt: 4,
      sparkleCnt: 5,
    });

    MockWebSocket.instances[0].receive({
      type: "profile_update",
      sender_id: "user-2",
      nickname: "New Name",
      image: "new.png",
    });

    expect(useMessageStore.getState().messages[0]).toMatchObject({
      nickname: "New Name",
      image: "new.png",
    });
  });

  it("sends message, edit, emoji, and profile payloads over the same socket", async () => {
    const { RealtimeWebSocketClient } = await import("../RealtimeWebSocketClient");

    render(<RealtimeWebSocketClient workspaceId="1" tabId="2" />);
    const socket = MockWebSocket.instances[0];

    useMessageStore.setState({
      message: "new message",
      fileUrl: "file.png",
      sendFlag: true,
    });

    await waitFor(() => expect(socket.sent).toHaveLength(1));
    expect(JSON.parse(socket.sent[0])).toEqual({
      type: "send",
      sender_id: "user-1",
      content: "new message",
      file_url: "file.png",
    });
    expect(alarmSSEMock).toHaveBeenCalledWith("1", "2", "new_message");
    expect(webPushMock).toHaveBeenCalledWith("1", "2", "new message");
    expect(useMessageStore.getState().fileUrl).toBeNull();
    expect(useMessageStore.getState().sendFlag).toBe(false);

    useMessageStore.getState().setEditMsgFlag(303, "edited message");

    await waitFor(() => expect(socket.sent).toHaveLength(2));
    expect(JSON.parse(socket.sent[1])).toEqual({
      type: "edit",
      msg_id: 303,
      content: "edited message",
    });
    expect(useMessageStore.getState().editMsgFlag).toBe(false);

    useMessageStore.setState({
      pendingEmojiUpdates: [{ msgId: 303, emojiType: "clap", emojiAction: "like" }],
      sendEmojiFlag: true,
    });

    await waitFor(() => expect(socket.sent).toHaveLength(3));
    expect(JSON.parse(socket.sent[2])).toEqual({
      type: "emoji",
      messageId: 303,
      userId: "user-1",
      action: "like",
      emojiType: "clap",
    });
    expect(useMessageStore.getState().pendingEmojiUpdates).toEqual([]);
    expect(useMessageStore.getState().inFlightEmojiUpdates).toEqual([
      { msgId: 303, emojiType: "clap", emojiAction: "like" },
    ]);

    useMessageStore.setState({
      editTarget: { nickname: "Profile Name", image: "profile.png" },
      sendEditFlag: true,
    });

    await waitFor(() => expect(socket.sent).toHaveLength(4));
    expect(JSON.parse(socket.sent[3])).toEqual({
      type: "profile",
      sender_id: "user-1",
      nickname: "Profile Name",
      image: "profile.png",
    });
    expect(useTabStore.getState().needsRefresh).toBe(true);
    expect(MockBroadcastChannel.posted).toContainEqual({
      type: "profile_updated",
      data: {
        type: "profile",
        sender_id: "user-1",
        nickname: "Profile Name",
        image: "profile.png",
      },
    });
  });
});
