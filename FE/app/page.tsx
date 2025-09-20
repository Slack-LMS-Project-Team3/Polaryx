"use client";

const BASE = process.env.NEXT_PUBLIC_BASE;

import "@/styles/globals.css";
import React, { useMemo } from "react";
import { LoginButton } from "../components/login/LoginButton";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { reissueAccessToken } from "@/apis/authApi";

type Star = {
  id: number;
  size: number; // px 단위
  top: number; // % 단위
  left: number; // % 단위
  delay: number; // s
  duration: number; // s
};

const Stars: React.FC<{ count?: number }> = ({ count = 100 }) => {
  const stars: Star[] = useMemo(() => {
    return Array.from({ length: count }).map((_, i) => ({
      id: i,
      size: Math.random() * 1 + 1, // 1 ~ 2px
      top: Math.random() * 100, // 0% ~ 100%
      left: Math.random() * 100,
      delay: Math.random() * 1, // 0s ~ 1s
      duration: Math.random() * 1 + 1, // 1s ~ 2s
    }));
  }, [count]);

  return (
    <>
      {stars.map((s) => (
        <span
          key={s.id}
          className="twinkle"
          style={{
            width: `${s.size}px`,
            height: `${s.size}px`,
            top: `${s.top}%`,
            left: `${s.left}%`,
            animationDelay: `${s.delay}s`,
            animationDuration: `${s.duration}s`,
          }}
        />
      ))}
    </>
  );
};

export default function Page() {
  const router = useRouter();

  useEffect(() => {
    const getToken = async () => {
      try {
        const token = localStorage.getItem("access_token");

        const res = await fetch(`${BASE}/api/auth/check`, {
          headers: { authorization: `Bearer ${token}` },
        });

        if (!res.ok) {
          if (res.status === 401) {
            const errbody: { detail?: string } = await res.clone().json();

            console.log(errbody.detail);
            if (errbody.detail == "EXPIRED TOKEN") {
              console.log(1);
              await reissueAccessToken("EXPIRED TOKEN");
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error) {
          console.error(err.message);
        }
      }
    };

    getToken();
  }, [router]);
  return (
    <div className="flex flex-col relative flex justify-center items-center h-screen overflow-hidden bg-black">
      {/* 별만 있는 레이어 */}
      <Stars count={150} />

      {/* 로고 */}
      <div className="justify-center gap-10 z-10 p-8 bg-black backdrop-blur-md rounded-2xl flex flex-col items-center w-[30%] mt-15">
        <div className="flex flex-row items-center mb-15">
          <img src="/logo.png" alt="SLAM Logo" className="w-15 h-15" />
          <h1 className="ml-3 kaisei-harunoumi-bold text-5xl font-extrabold text-white text-center tracking-[0.5rem] whitespace-nowrap">
            Polaryx
            <span className="ml-1 -translate-y-8 inline-block text-blue-200">
              .
            </span>
          </h1>
        </div>
        {/* 구글 로그인 버튼 */}
        <LoginButton />
      </div>
    </div>
  );
}
