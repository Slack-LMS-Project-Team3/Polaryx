"use client";

const BASE = process.env.NEXT_PUBLIC_BASE;
const NEXT_PUBLIC_WS = process.env.NEXT_PUBLIC_WS;


import { useEffect, useRef } from "react";
import { useMessageStore } from "@/store/messageStore";
import { useTabStore } from "@/store/tabStore";
import { useProfileStore } from "@/store/profileStore";
import { jwtDecode } from "jwt-decode";

interface JWTPayload {
  user_id: string;
}

function stripTags(html: string): string {
  return html.replace(/<[^>]+>/g, "");
}

export const WebSocketProfileClient = ({
  workspaceId,
  tabId,
}: {
  workspaceId: string;
  tabId: string;
}) => {
  const socketRef = useRef<WebSocket | null>(null);
  const { sendEditFlag, editTarget, setSendEditFlag, updateUserProfile } = useMessageStore();
  const { refreshTabs } = useTabStore();
  const { profile, updateProfile } = useProfileStore();

  useEffect(() => {
    {
      console.log("websocket_client");
    }
  });

  // 다른 탭에서 프로필 변경 감지
  useEffect(() => {
    const channel = new BroadcastChannel('profile_updates');
    
    channel.onmessage = (event) => {
      if (event.data.type === 'profile_updated') {
        const { sender_id, nickname, image } = event.data.data;
        
        // 프로필 업데이트 적용
        const editThings = {
          "nickname": nickname,
          "image": image === 'none' ? undefined : image
        };
        
        updateUserProfile(sender_id, editThings);
        updateProfile(sender_id, editThings['nickname'], editThings['image']);
      }
    };

    return () => {
      channel.close();
    };
  }, [updateUserProfile, updateProfile]);

  useEffect(() => {
    console.log("new web sokcet");
    const socket = new WebSocket(
      `${NEXT_PUBLIC_WS}/api/ws/profile/${workspaceId}/${tabId}`,
    );

    socketRef.current = socket;

    socket.onopen = () => {
      console.log("websocket connected");
    };

    socket.onmessage = (event) => {
      try {
        const rawMsg = JSON.parse(event.data);
        console.log("받은 메시지:", rawMsg); // 전체 메시지 로그
        
        const targetUserId = rawMsg.sender_id;
        const editThings ={
            "nickname": rawMsg.nickname,
            "image": rawMsg.image == 'none' ? undefined:rawMsg.image
        };

        console.log("asdgad")
        // file_url을 fileUrl로 변환하고 원본 제거
        updateUserProfile(targetUserId, editThings);
        updateProfile(targetUserId, editThings['nickname'], editThings['image']);
      } catch {
        console.warn("Invalid message format: ", event.data);
      }
    };

    socket.onerror = (error) => {
      console.error("❗ WebSocket 에러 발생", error);
      // UI에 에러 표시 
    };

    socket.onclose = () => {
      console.log("WebSocket closed");
    };

    return () => {
      socket.close();
    };
  }, [workspaceId, tabId]);

  // 프로필 수정 감지
  useEffect(() => {
    if (
        sendEditFlag &&
        editTarget &&
        socketRef.current?.readyState === WebSocket.OPEN
    ) {
      const token = localStorage.getItem("access_token");

      if (!token) {
        console.log("토큰없당"); // 추후 수정
        return;
      }

      const { user_id } = jwtDecode<JWTPayload>(token);

      const payload = {
        sender_id: user_id,
        nickname: editTarget["nickname"],
        image: editTarget["image"],
      };

      socketRef.current.send(JSON.stringify(payload));
      
      // 다른 탭에도 프로필 변경 알림
      const channel = new BroadcastChannel('profile_updates');
      channel.postMessage({
        type: 'profile_updated',
        data: payload
      });
      channel.close();
      
      refreshTabs();
      setSendEditFlag(false); // 전송 후 플래그 초기화
      useMessageStore.getState().setFileUrl(null);
    }
  }, [sendEditFlag, setSendEditFlag]);

  return <div>{/* 필요시 메시지 입력창/버튼 등 추가 */}</div>;
};