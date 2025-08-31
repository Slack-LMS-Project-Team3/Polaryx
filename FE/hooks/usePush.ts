"use client";
import { useEffect } from "react";
import { jwtDecode } from "jwt-decode";

function urlBase64ToUint8Array(base64String: string) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);

  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

const PUBLIC_KEY = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY as
  | string
  | undefined;
const BASE = process.env.NEXT_PUBLIC_BASE;

export function usePush() {
  useEffect(() => {
    if (!PUBLIC_KEY || !BASE) return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return;
    }

    // const handleMessage = (event: MessageEvent) => {
    //   if (event.data && event.data.type === 'play-sound' && event.data.sound) {
    //     const audio = new Audio(event.data.sound);
    //     audio.play().catch(() => {});
    //   }
    // };

    const handleMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === "play-sound" && event.data.sound) {
        const audio = new Audio(event.data.sound);

        // 사용자 상호작용이 필요한 경우를 위한 처리
        const playPromise = audio.play();

        if (playPromise !== undefined) {
          playPromise
            .then(() => {
              // 재생 성공
              console.log("알람 소리 재생됨");
            })
            .catch((error) => {
              console.log("알람 소리 재생 실패:", error);
              // 사용자 상호작용이 필요한 경우 알림
              if (error.name === "NotAllowedError") {
                console.log("사용자 상호작용이 필요합니다");
              }
            });
        }
      }
    };
    navigator.serviceWorker.addEventListener("message", handleMessage);
    Notification.requestPermission().then(async (perm) => {
      if (perm !== "granted") return;
      const reg = await navigator.serviceWorker.register("/sw.js");
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(PUBLIC_KEY),
      });
      const token = localStorage.getItem("access_token");
      if (!token) return; // token이 없으면 중단

      const { user_id } = jwtDecode<{ user_id: string }>(token);
      await fetch(`${BASE}/api/push/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id, subscription: sub }),
      });
    });
    return () => {
      navigator.serviceWorker.removeEventListener("message", handleMessage);
    };
  }, []); // 한 번만 실행
}
