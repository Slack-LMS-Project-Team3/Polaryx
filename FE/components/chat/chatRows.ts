export type ChatMessageId = number | string;

export interface ChatMessage {
  tabId?: number;
  senderId?: string;
  msgId?: ChatMessageId;
  nickname: string;
  image?: string;
  content: string;
  createdAt?: string;
  fileUrl?: string | null;
  isUpdated?: number;
  checkCnt: number;
  prayCnt: number;
  sparkleCnt: number;
  clapCnt: number;
  likeCnt: number;
  myToggle: Record<string, boolean>;
}

export interface DateChatRow {
  type: "date";
  key: string;
  timestamp: number;
}

export interface MessageChatRow {
  type: "message";
  key: string;
  message: ChatMessage;
  showProfile: boolean;
}

export type ChatRow = DateChatRow | MessageChatRow;

export function dayStart(iso: string) {
  const d = new Date(iso);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function messageRowKey(message: ChatMessage) {
  const id = message.msgId;

  if (typeof id === "number") {
    return `msg:${id}`;
  }

  if (typeof id === "string" && id.length > 0) {
    return id.startsWith("temp_") ? `temp:${id}` : `msg:${id}`;
  }

  return `temp:${message.senderId ?? "unknown"}:${message.createdAt ?? "unknown"}:${message.content}`;
}

export function shouldShowProfile(
  current: ChatMessage,
  previous?: ChatMessage,
) {
  if (
    !previous ||
    previous.nickname !== current.nickname ||
    !previous.createdAt ||
    !current.createdAt
  ) {
    return true;
  }

  const diff = new Date(current.createdAt).getTime() - new Date(previous.createdAt).getTime();
  return diff > 5 * 60 * 1000;
}

export function buildChatRows(messages: ChatMessage[]): ChatRow[] {
  const rows: ChatRow[] = [];

  messages.forEach((message, index) => {
    const previous = messages[index - 1];
    const currentDay = message.createdAt ? dayStart(message.createdAt) : null;
    const previousDay = previous?.createdAt ? dayStart(previous.createdAt) : null;

    if (currentDay !== null && (previousDay === null || currentDay !== previousDay)) {
      rows.push({
        type: "date",
        key: `date:${currentDay}`,
        timestamp: currentDay,
      });
    }

    rows.push({
      type: "message",
      key: messageRowKey(message),
      message,
      showProfile: shouldShowProfile(message, previous),
    });
  });

  return rows;
}
