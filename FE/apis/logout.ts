import { fetchWithAuth } from "./authApi";

const BASE = process.env.NEXT_PUBLIC_BASE;

export async function logout() {
  // api 호출 - fetchWithAuth가 자동으로 토큰 추가 및 체크
  const res = await fetchWithAuth(`${BASE}/api/auth/logout`, {
    method: "DELETE",
    credentials: "include",
  });

  if (res == null) {
    return;
  }

  // 에러 처리
  if (!res.ok) {
    throw new Error(`Logout failed: ${res.status}`);
  }

  // 로그아웃 성공 시에만 토큰 삭제
  localStorage.clear();
  return res;
}
