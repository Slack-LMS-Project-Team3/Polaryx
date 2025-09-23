"use client";

const BASE = process.env.NEXT_PUBLIC_BASE;

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useMessageStore } from "@/store/messageStore";
import { useTabStore } from "@/store/tabStore";

interface SSEPayload {
  type: "new_message" | "invited_to_tab"; // 타입 2개임: 새 메시지 | 탭에 초대
  tab_id: number; // 메시지를 보낸 탭의 id
  sender_id?: string; // 메시지 보낸 유저의 id
}

export function SSEListener() {
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

    const url = `${BASE}/api/sse/notifications?workspaceId=${workspaceId}`;
    const controller = new AbortController();

    async function connectSSE() {
      try {
        const response = await fetch(url, {
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

        if (!reader) return;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('event:')) {
              const eventType = line.substring(6).trim();
              continue;
            }

            if (line.startsWith('data:')) {
              const data = line.substring(5).trim();

              if (data === 'p') { // ping
                console.log("SSE: 유지 ping");
                continue;
              }

              try {
                const payload: SSEPayload = JSON.parse(data);

                if (payload.type === 'new_message') {
                  console.log("SSE: 새 메세지 도착");
                  if (payload.tab_id.toString() !== tabId) {
                    incUnread(payload.tab_id);
                  }
                } else if (payload.type === 'invited_to_tab') {
                  console.log("SSE: 새로운 탭 초대");
                  addInvitedTab(payload.tab_id);
                  refreshTabs();
                }
              } catch (e) {
                console.error("SSE data parse error:", e);
              }
            }
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          console.log("SSE: 연결 끊김", error);
        }
      }
    }

    connectSSE();

    return () => {
      controller.abort();
    };
  }, [workspaceId, incUnread, refreshTabs, addInvitedTab, tabId]);

  return null;
}
