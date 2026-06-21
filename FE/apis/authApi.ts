const BASE = process.env.NEXT_PUBLIC_BASE!;

export interface RefreshResponse {
  access_token: string;
}

export const authRedirect = {
  home: () => {
    window.location.href = "/";
  },
};

// fetchWithAuth 으로 다시 만들기.
export async function fetchWithAuth(
  input: RequestInfo,
  init: RequestInit = {}
): Promise<Response | null> {
  const accessToken = localStorage.getItem("access_token");

  if (!accessToken) {
    console.warn("No access token available.");
    return null;
  }

  // Authorization 헤더 추가
  const authHeaders = new Headers(init.headers);
  authHeaders.set("Authorization", `Bearer ${accessToken}`);

  init = {
    ...init,
    headers: authHeaders,
    credentials: "include",
  };

  // 1차 요청
  let res = await fetch(input, init);

  // 만약 토큰 만료 등으로 실패하면
  if (res.status === 401) {
    console.log("401 fetch auth")
    try {
      const errBody = await res.clone().json();
      console.log("401 fetch auth", errBody)
      const detail = errBody?.message;
      
      if (detail === "EXPIRED TOKEN") {
        console.log("401 fetch auth, EXPIRED TOKEN")
        const newAccessToken = await reissueAccessToken("EXPIRED TOKEN");

        if (!newAccessToken) {
          // window.location.href = "/";
          console.log("** no new ACcesssToken  **")
          return null;
        }
        console.log("**** Acess Token 받기 성공 ***");

        // Authorization 다시 업데이트
        const retryHeaders = new Headers(init.headers);
        retryHeaders.set("Authorization", `Bearer ${newAccessToken}`);

        const retryInit: RequestInit = {
          ...init,
          headers: retryHeaders,
          credentials: "include",
        };

        // 재요청
        res = await fetch(input, retryInit);
        return res;
      } else if (detail === "INVALID ACCESS TOKEN" || detail === "NOT INVALID REFRESH TOKEN") {
        console.warn("유효하지 않은 토큰");
        authRedirect.home();
        return null;
      }
    } catch (e) {
      console.log("401 fetch auth, err", e)
      console.error(input," json parse 실패", e);
      return null;
    }
  }
  else {
    console.log("not 401: ", res.status);
  }

  return res;
}

export async function reissueAccessToken(details: string): Promise<any> {
  
  console.log("access_token 삭제");
  localStorage.removeItem("access_token");
  
  const test = localStorage.getItem("access_token");
  console.log(test)
  
  if (details == "EXPIRED TOKEN") {
    console.log("in reissueAccessToken, EXPIRED TOKEN");
    const res = await fetch(`${BASE}/api/auth/refresh`, {
      method: "POST",
      credentials: "include", // httpOnly 쿠키에 담긴 refresh_token 자동 전송
    });

    if (!res.ok) {
        console.log("ACCESS TOKEN 재발급 실패")
    }
    else {
      const { access_token: newToken } = (await res.json()) as RefreshResponse;
      if (!newToken) {
        console.warn("ACCESS TOKEN 재발급 응답에 access_token이 없습니다");
        return null;
      }
      console.log(newToken);
      localStorage.setItem("access_token", newToken);
      return newToken;
    }
  }
  else if (details == "INVALID ACCESS TOKEN") {
    console.log("INVALID ACCESS TOKEN")
  }
  else {
    console.log("NOT INVALID REFRESH TOKEN")
  }

  return null;
}
