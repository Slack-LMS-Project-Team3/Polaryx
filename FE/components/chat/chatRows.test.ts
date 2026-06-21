import { describe, expect, it } from "vitest";
import { buildChatRows, dayStart } from "./chatRows";
import type { ChatMessage } from "./chatRows";

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    senderId: "user-1",
    msgId: 1,
    nickname: "Mina",
    image: "/user_default.png",
    content: "hello",
    createdAt: "2026-06-21T10:00:00+09:00",
    fileUrl: null,
    isUpdated: 0,
    checkCnt: 0,
    prayCnt: 0,
    sparkleCnt: 0,
    clapCnt: 0,
    likeCnt: 0,
    myToggle: {
      check: false,
      pray: false,
      sparkle: false,
      clap: false,
      like: false,
    },
    ...overrides,
  };
}

describe("buildChatRows", () => {
  it("creates stable date and message row keys without array indexes", () => {
    const rows = buildChatRows([
      message({ msgId: 10, createdAt: "2026-06-21T10:00:00+09:00" }),
      message({ msgId: "temp_abc", createdAt: "2026-06-21T10:01:00+09:00" }),
      message({ msgId: 11, createdAt: "2026-06-22T09:00:00+09:00" }),
    ]);

    expect(rows.map((row) => row.key)).toEqual([
      `date:${dayStart("2026-06-21T10:00:00+09:00")}`,
      "msg:10",
      "temp:temp_abc",
      `date:${dayStart("2026-06-22T09:00:00+09:00")}`,
      "msg:11",
    ]);
  });

  it("preserves the five-minute same-nickname profile grouping rule", () => {
    const rows = buildChatRows([
      message({ msgId: 1, nickname: "Mina", createdAt: "2026-06-21T10:00:00+09:00" }),
      message({ msgId: 2, nickname: "Mina", createdAt: "2026-06-21T10:04:59+09:00" }),
      message({ msgId: 3, nickname: "Mina", createdAt: "2026-06-21T10:06:00+09:00" }),
      message({ msgId: 4, nickname: "Joon", createdAt: "2026-06-21T10:07:00+09:00" }),
    ]);

    const messageRows = rows.filter((row) => row.type === "message");

    expect(messageRows.map((row) => row.showProfile)).toEqual([
      true,
      false,
      false,
      true,
    ]);
  });
});
