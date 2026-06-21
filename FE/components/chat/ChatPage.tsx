import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMessageStore } from "@/store/messageStore";
import { RealtimeWebSocketClient } from "../ws/RealtimeWebSocketClient";
import { ShowDate } from "./ShowDate";
import { ChatProfile } from "./ChatProfile";
import { getMessages } from "@/apis/messageApi";
import { Skeleton } from "@/components/ui/skeleton";
import { SSEListener } from "../sse/SSEListener";
import { buildChatRows } from "./chatRows";
import type { ChatMessage, ChatRow } from "./chatRows";

const TOP_FETCH_THRESHOLD_PX = 30;
const BOTTOM_FOLLOW_THRESHOLD_PX = 100;
const VIRTUAL_OVERSCAN_ROWS = 10;

function SkeletonChat() {
  return (
    <div className="flex px-[8px] py-[4.5px]">
      <Skeleton className="w-[40px] h-[40px] mt-1 mr-[8px] rounded-lg bg-gray-300" />
      <div className="mt-1 space-y-2">
        <Skeleton className="h-4 w-[70px] bg-gray-300" />
        <Skeleton className="h-10 w-[300px] bg-gray-300" />
      </div>
    </div>
  );
}

function mapApiMessage(msg: any): ChatMessage {
  return {
    tabId: msg.tab_id,
    senderId: msg.sender_id,
    msgId: msg.msg_id,
    nickname: msg.nickname ?? "",
    content: msg.content ?? "",
    image: msg.image,
    createdAt: msg.created_at,
    isUpdated: msg.is_updated ?? 0,
    fileUrl: msg.file_url ?? null,
    checkCnt: msg.e_check_cnt ?? 0,
    clapCnt: msg.e_clap_cnt ?? 0,
    likeCnt: msg.e_like_cnt ?? 0,
    sparkleCnt: msg.e_sparkle_cnt ?? 0,
    prayCnt: msg.e_pray_cnt ?? 0,
    myToggle: msg.my_toggle ?? {
      check: false,
      pray: false,
      sparkle: false,
      clap: false,
      like: false,
    },
  };
}

function formatMessageTime(createdAt?: string) {
  if (!createdAt) return " ";

  return new Date(createdAt).toLocaleTimeString("ko-KR", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function isNearBottom(el: HTMLElement) {
  return (
    el.scrollHeight - el.scrollTop - el.clientHeight <=
    BOTTOM_FOLLOW_THRESHOLD_PX
  );
}

function findRenderedRow(
  container: HTMLElement,
  key: string,
): HTMLElement | undefined {
  return Array.from(
    container.querySelectorAll<HTMLElement>("[data-chat-row-key]"),
  ).find((node) => node.dataset.chatRowKey === key);
}

function firstNumericMessageId(messages: ChatMessage[]) {
  return messages.find((message) => typeof message.msgId === "number")
    ?.msgId as number | undefined;
}

function rowActionMessageId(row: Extract<ChatRow, { type: "message" }>) {
  return row.message.msgId ?? row.key;
}

function rowEstimate(row?: ChatRow) {
  return row?.type === "date" ? 44 : 76;
}

function observeScrollElementRect(
  instance: { scrollElement: Element | null },
  cb: (rect: { width: number; height: number }) => void,
) {
  const element = instance.scrollElement as HTMLElement | null;
  if (!element) return undefined;

  const emitRect = () => {
    const rect = element.getBoundingClientRect();
    cb({
      width: element.clientWidth || rect.width || 1024,
      height: element.clientHeight || rect.height || 640,
    });
  };

  emitRect();

  if (typeof ResizeObserver === "undefined") {
    return undefined;
  }

  const observer = new ResizeObserver(emitRect);
  observer.observe(element);
  return () => observer.disconnect();
}

// 채팅방 내 채팅
export function ChatPage({
  workspaceId,
  tabId,
  className = "",
}: {
  workspaceId: string;
  tabId: string;
  className?: string;
}) {
  const { messages, prependMessages, setMessages } = useMessageStore();

  const containerRef = useRef<HTMLDivElement>(null);
  const isFetching = useRef(false);
  const shouldFollowBottomRef = useRef(true);
  const needsInitialScrollRef = useRef(false);
  const pendingPrependAnchorRef = useRef<{
    key: string;
    top: number;
    scrollTop: number;
    totalSize: number;
  } | null>(null);

  const [editingMsgId, setEditingMsgId] = useState<
    NonNullable<ChatMessage["msgId"]> | null
  >(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isBottom, setIsBottom] = useState(false);

  const rows = useMemo(() => buildChatRows(messages), [messages]);
  const lastRowKey = rows[rows.length - 1]?.key ?? "";
  const layoutSignal = useMemo(
    () =>
      messages
        .map(
          (message) =>
            `${message.msgId}:${message.content}:${message.fileUrl ?? ""}:${message.isUpdated}:${message.checkCnt}:${message.prayCnt}:${message.sparkleCnt}:${message.clapCnt}:${message.likeCnt}:${message.image ?? ""}`,
        )
        .join("|"),
    [messages],
  );

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => containerRef.current,
    estimateSize: (index) => rowEstimate(rows[index]),
    getItemKey: (index) => rows[index]?.key ?? `missing:${index}`,
    overscan: VIRTUAL_OVERSCAN_ROWS,
    initialRect: { width: 1024, height: 640 },
    observeElementRect: observeScrollElementRect,
    useFlushSync: false,
  });

  const virtualItems = rowVirtualizer.getVirtualItems();
  const scrollOffset = rowVirtualizer.scrollOffset ?? 0;
  const firstVisibleIndex = useMemo(() => {
    const firstVisible = virtualItems.find((item) => item.end > scrollOffset);
    return firstVisible?.index ?? virtualItems[0]?.index ?? -1;
  }, [scrollOffset, virtualItems]);
  const activeDateTimestamp = useMemo(() => {
    if (firstVisibleIndex < 0) return null;

    for (let index = firstVisibleIndex; index >= 0; index -= 1) {
      const row = rows[index];
      if (row?.type === "date") return row.timestamp;
    }

    return null;
  }, [firstVisibleIndex, rows]);
  const showStickyDate =
    activeDateTimestamp !== null && rows[firstVisibleIndex]?.type !== "date";

  const scrollToLatest = useCallback(() => {
    if (rows.length === 0) return;

    requestAnimationFrame(() => {
      rowVirtualizer.scrollToIndex(rows.length - 1, { align: "end" });
    });
  }, [rowVirtualizer, rows.length]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setIsLoading(true);
      const res = await getMessages(workspaceId, tabId, undefined);

      if (cancelled) return;

      if (res.messages && res.messages.length) {
        setMessages(res.messages.map(mapApiMessage));
      } else {
        setMessages([]);
      }

      needsInitialScrollRef.current = true;
      shouldFollowBottomRef.current = true;
      setIsBottom(true);
      setIsLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [workspaceId, tabId, setMessages]);

  useLayoutEffect(() => {
    const anchor = pendingPrependAnchorRef.current;

    if (anchor) {
      const anchorIndex = rows.findIndex((row) => row.key === anchor.key);
      pendingPrependAnchorRef.current = null;
      const restoreBySizeDelta = () => {
        const container = containerRef.current;
        if (!container) return;

        const sizeDelta = rowVirtualizer.getTotalSize() - anchor.totalSize;
        container.scrollTop = anchor.scrollTop + Math.max(0, sizeDelta);
      };

      if (anchorIndex >= 0) {
        requestAnimationFrame(() => {
          rowVirtualizer.scrollToIndex(anchorIndex, { align: "start" });

          requestAnimationFrame(() => {
            const container = containerRef.current;
            if (!container) return;

            const anchorElement = findRenderedRow(container, anchor.key);
            if (!anchorElement) {
              restoreBySizeDelta();
              return;
            }

            container.scrollTop +=
              anchorElement.getBoundingClientRect().top - anchor.top;
          });
        });
      } else {
        requestAnimationFrame(restoreBySizeDelta);
      }

      return;
    }

    if (needsInitialScrollRef.current) {
      needsInitialScrollRef.current = false;
      scrollToLatest();
      return;
    }

    if (shouldFollowBottomRef.current) {
      scrollToLatest();
    }
  }, [lastRowKey, rows, rowVirtualizer, scrollToLatest]);

  useEffect(() => {
    rowVirtualizer.measure();

    if (shouldFollowBottomRef.current || isBottom) {
      scrollToLatest();
    }
  }, [editingMsgId, isBottom, layoutSignal, rowVirtualizer, scrollToLatest]);

  const capturePrependAnchor = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const scrollTop = container.scrollTop;
    const firstVisibleItem = rowVirtualizer
      .getVirtualItems()
      .find((item) => item.end > scrollTop && rows[item.index]?.type === "message");

    if (!firstVisibleItem) return;

    const row = rows[firstVisibleItem.index];
    if (!row) return;

    const renderedRow = findRenderedRow(container, row.key);
    pendingPrependAnchorRef.current = {
      key: row.key,
      top:
        renderedRow?.getBoundingClientRect().top ??
        container.getBoundingClientRect().top,
      scrollTop,
      totalSize: rowVirtualizer.getTotalSize(),
    };
  }, [rowVirtualizer, rows]);

  const handleScroll = async (event: React.UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    const nearTop = el.scrollTop < TOP_FETCH_THRESHOLD_PX;
    const nearBottom = !nearTop && isNearBottom(el);
    shouldFollowBottomRef.current = nearBottom;
    setIsBottom(nearBottom);

    if (!nearTop || isFetching.current) {
      return;
    }

    const oldestId = firstNumericMessageId(messages);
    if (oldestId === undefined) return;

    isFetching.current = true;
    shouldFollowBottomRef.current = false;
    setIsBottom(false);
    capturePrependAnchor();

    try {
      const res = await getMessages(workspaceId, tabId, oldestId);

      if (res.messages && res.messages.length > 0) {
        prependMessages(res.messages.map(mapApiMessage));
      } else {
        pendingPrependAnchorRef.current = null;
      }
    } finally {
      isFetching.current = false;
    }
  };

  const handleRowContentLoad = useCallback(
    (event: React.SyntheticEvent<HTMLDivElement>) => {
      const rowElement = event.currentTarget;
      rowVirtualizer.measureElement(rowElement);

      if (shouldFollowBottomRef.current) {
        scrollToLatest();
      }
    },
    [rowVirtualizer, scrollToLatest],
  );

  // 로딩 중이면, 스켈레톤 이미지 보여줌
  if (isLoading) {
    return (
      <div className="flex flex-col justify-start w-full">
        <div className="sticky top-1.5 mx-auto w-[120px] h-[28px] z-1 my-2">
          <Skeleton className="w-full h-full bg-gray-300 rounded-full" />
        </div>
        <div className="text-m min-h-0 pl-5 w-full">
          {Array.from({ length: 10 }).map((_, i) => (
            <SkeletonChat key={i} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-col w-full h-full min-h-0 ${className}`}>
      <SSEListener />
      <RealtimeWebSocketClient workspaceId={workspaceId} tabId={tabId} />
      <div
        className="relative flex-1 min-h-0 overflow-y-auto scrollbar-thin"
        ref={containerRef}
        data-testid="chat-scroll-container"
        onScroll={handleScroll}
      >
        {showStickyDate && (
          <div className="sticky top-1.5 z-10 h-0 pointer-events-none">
            <ShowDate timestamp={activeDateTimestamp} />
          </div>
        )}

        <div
          className="relative w-full"
          style={{ height: `${rowVirtualizer.getTotalSize()}px` }}
        >
          {virtualItems.map((virtualItem) => {
            const row = rows[virtualItem.index];
            if (!row) return null;

            if (row.type === "date") {
              return (
                <div
                  key={row.key}
                  data-index={virtualItem.index}
                  data-chat-row-key={row.key}
                  data-chat-row-type={row.type}
                  ref={rowVirtualizer.measureElement}
                  onLoadCapture={handleRowContentLoad}
                  className="absolute left-0 w-full"
                  style={{ top: `${virtualItem.start}px` }}
                >
                  <ShowDate timestamp={row.timestamp} sticky={false} />
                </div>
              );
            }

            const msgId = rowActionMessageId(row);

            return (
              <div
                key={row.key}
                data-index={virtualItem.index}
                data-chat-row-key={row.key}
                data-chat-row-type={row.type}
                ref={rowVirtualizer.measureElement}
                onLoadCapture={handleRowContentLoad}
                className="absolute left-0 w-full"
                style={{ top: `${virtualItem.start}px` }}
              >
                <ChatProfile
                  senderId={row.message.senderId || ""}
                  msgId={msgId}
                  imgSrc={row.message.image || "/user_default.png"}
                  nickname={row.message.nickname}
                  time={formatMessageTime(row.message.createdAt)}
                  content={row.message.content}
                  showProfile={row.showProfile}
                  fileUrl={row.message.fileUrl ?? null}
                  isUpdated={row.message.isUpdated ?? 0}
                  checkCnt={row.message.checkCnt}
                  prayCnt={row.message.prayCnt}
                  sparkleCnt={row.message.sparkleCnt}
                  clapCnt={row.message.clapCnt}
                  likeCnt={row.message.likeCnt}
                  myToggle={row.message.myToggle}
                  isEditMode={editingMsgId !== null && editingMsgId === msgId}
                  onStartEdit={() => setEditingMsgId(msgId)}
                  onEndEdit={() => setEditingMsgId(null)}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
