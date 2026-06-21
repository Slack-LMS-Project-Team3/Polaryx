"use client";

import { useEffect, useRef } from "react";
import { jwtDecode } from "jwt-decode";
import { alarmSSE, webPush } from "@/apis/notificationApi";
import { useMessageStore } from "@/store/messageStore";
import { useProfileStore } from "@/store/profileStore";
import { useTabStore } from "@/store/tabStore";

const NEXT_PUBLIC_WS = process.env.NEXT_PUBLIC_WS;

interface JWTPayload {
  user_id: string;
}

interface RealtimeWebSocketClientProps {
  workspaceId: string;
  tabId: string;
}

function profileImage(image: string | undefined) {
  return image === "none" ? undefined : image;
}

export function RealtimeWebSocketClient({
  workspaceId,
  tabId,
}: RealtimeWebSocketClientProps) {
  const socketRef = useRef<WebSocket | null>(null);
  const {
    message,
    sendFlag,
    editMsgFlag,
    sendEmojiFlag,
    sendEditFlag,
    editMessage,
    editTarget,
    fileUrl,
    pendingEmojiUpdates,
    setSendFlag,
    cleanEditMsgFlag,
    setSendEmojiFlag,
    setSendEditFlag,
    clearPendingEmojiUpdates,
    addInFlightEmojiUpdates,
    updateEmojiCounts,
    updateMessage,
    updateUserProfile,
  } = useMessageStore();
  const { refreshTabs } = useTabStore();
  const { updateProfile } = useProfileStore();

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;

    const channel = new BroadcastChannel("profile_updates");

    channel.onmessage = (event) => {
      if (event.data.type !== "profile_updated") return;

      const { sender_id, nickname, image } = event.data.data;
      const editThings = {
        nickname,
        image: profileImage(image),
      };

      updateUserProfile(sender_id, editThings);
      updateProfile(sender_id, editThings.nickname, editThings.image);
    };

    return () => {
      channel.close();
    };
  }, [updateUserProfile, updateProfile]);

  useEffect(() => {
    const socket = new WebSocket(`${NEXT_PUBLIC_WS}/api/ws/${workspaceId}/${tabId}`);
    socketRef.current = socket;

    socket.onopen = () => {
      console.log("Realtime WebSocket connected");
    };

    socket.onmessage = (event) => {
      try {
        const rawMsg = JSON.parse(event.data);

        switch (rawMsg.type) {
          case "send": {
            const { file_url, ...msgWithoutFileUrl } = rawMsg;
            const msg: any = {
              ...msgWithoutFileUrl,
              fileUrl: file_url,
              senderId: rawMsg.sender_id,
              msgId: rawMsg.message_id,
              createdAt: rawMsg.created_at,
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
            };

            useMessageStore.getState().appendMessage(msg);

            const token = localStorage.getItem("access_token");
            if (!token) return;

            const { user_id } = jwtDecode<JWTPayload>(token);
            if (rawMsg.sender_id === user_id) {
              console.log("내 메시지이면서 현재 채널이면 알림 생략");
            }
            break;
          }
          case "edit":
            updateMessage(rawMsg.message_id, rawMsg.content);
            break;
          case "emoji_update":
            updateEmojiCounts(rawMsg.messageId, rawMsg);
            break;
          case "profile_update": {
            const editThings = {
              nickname: rawMsg.nickname,
              image: profileImage(rawMsg.image),
            };

            updateUserProfile(rawMsg.sender_id, editThings);
            updateProfile(rawMsg.sender_id, editThings.nickname, editThings.image);
            break;
          }
          default:
            console.warn("Unsupported realtime message type:", rawMsg.type);
        }
      } catch {
        console.warn("Invalid realtime message format: ", event.data);
      }
    };

    socket.onerror = (error) => {
      console.error("Realtime WebSocket error", error);
    };

    socket.onclose = () => {
      console.log("Realtime WebSocket closed");
    };

    return () => {
      socket.close();
    };
  }, [workspaceId, tabId, updateEmojiCounts, updateMessage, updateUserProfile, updateProfile]);

  useEffect(() => {
    if (!sendFlag || !message || socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
      console.log("토큰없당");
      return;
    }

    const { user_id } = jwtDecode<JWTPayload>(token);
    const payload = {
      type: "send",
      sender_id: user_id,
      content: message,
      file_url: fileUrl,
    };

    void alarmSSE(workspaceId, tabId, "new_message");
    void webPush(workspaceId, tabId, payload.content);
    socketRef.current.send(JSON.stringify(payload));
    useMessageStore.getState().setFileUrl(null);
    setSendFlag(false);
  }, [sendFlag, message, fileUrl, workspaceId, tabId, setSendFlag]);

  useEffect(() => {
    if (!editMsgFlag || !editMessage || socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    socketRef.current.send(
      JSON.stringify({
        type: "edit",
        msg_id: editMessage.msgId,
        content: editMessage.content,
      }),
    );
    cleanEditMsgFlag();
  }, [editMsgFlag, editMessage, cleanEditMsgFlag]);

  useEffect(() => {
    if (
      !sendEmojiFlag ||
      socketRef.current?.readyState !== WebSocket.OPEN ||
      pendingEmojiUpdates.length === 0
    ) {
      return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
      console.log("토큰없당");
      return;
    }

    const { user_id } = jwtDecode<JWTPayload>(token);

    pendingEmojiUpdates.forEach((update) => {
      socketRef.current?.send(
        JSON.stringify({
          type: "emoji",
          messageId: update.msgId,
          userId: user_id,
          action: update.emojiAction,
          emojiType: update.emojiType,
        }),
      );
    });

    addInFlightEmojiUpdates(pendingEmojiUpdates);
    clearPendingEmojiUpdates();
    setSendEmojiFlag(false);
  }, [
    sendEmojiFlag,
    pendingEmojiUpdates,
    clearPendingEmojiUpdates,
    addInFlightEmojiUpdates,
    setSendEmojiFlag,
  ]);

  useEffect(() => {
    if (!sendEditFlag || !editTarget || socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
      console.log("토큰없당");
      return;
    }

    const { user_id } = jwtDecode<JWTPayload>(token);
    const payload = {
      type: "profile",
      sender_id: user_id,
      nickname: editTarget.nickname,
      image: editTarget.image,
    };

    socketRef.current.send(JSON.stringify(payload));

    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel("profile_updates");
      channel.postMessage({
        type: "profile_updated",
        data: payload,
      });
      channel.close();
    }

    refreshTabs();
    setSendEditFlag(false);
    useMessageStore.getState().setFileUrl(null);
  }, [sendEditFlag, editTarget, refreshTabs, setSendEditFlag]);

  return null;
}
