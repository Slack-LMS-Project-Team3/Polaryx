import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const API_BASE = "https://api.example.test";

const navigationMocks = vi.hoisted(() => ({
  params: new URLSearchParams(),
  push: vi.fn(),
  replace: vi.fn(),
}));

const authMocks = vi.hoisted(() => ({
  fetchPermissions: vi.fn(),
  jwtDecode: vi.fn(),
  setUserId: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: navigationMocks.push,
    replace: navigationMocks.replace,
  }),
  useSearchParams: () => ({
    get: (key: string) => navigationMocks.params.get(key),
  }),
}));

vi.mock("jwt-decode", () => ({
  jwtDecode: authMocks.jwtDecode,
}));

vi.mock("@/store/myPermissionsStore", () => ({
  useMyPermissionsStore: () => ({
    fetchPermissions: authMocks.fetchPermissions,
  }),
}));

vi.mock("@/store/myUserStore", () => ({
  useMyUserStore: {
    getState: () => ({
      setUserId: authMocks.setUserId,
    }),
  },
}));

function createMemoryStorage(): Storage {
  const store = new Map<string, string>();

  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => store.delete(key),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
}

async function loadAuthCallbackPage() {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_BASE", API_BASE);
  return (await import("./AuthCallbackPage")).default;
}

describe("AuthCallbackPage", () => {
  beforeEach(() => {
    navigationMocks.params = new URLSearchParams();
    navigationMocks.push.mockReset();
    navigationMocks.replace.mockReset();
    authMocks.fetchPermissions.mockReset();
    authMocks.fetchPermissions.mockResolvedValue(undefined);
    authMocks.jwtDecode.mockReset();
    authMocks.jwtDecode.mockReturnValue({ user_id: "user-1" });
    authMocks.setUserId.mockReset();
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("localStorage", createMemoryStorage());
  });

  it("renders the existing loading UI while a valid code request is pending", async () => {
    navigationMocks.params = new URLSearchParams({
      code: "google-code",
      scope: "email",
      prompt: "select_account",
    });
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
    const AuthCallbackPage = await loadAuthCallbackPage();

    render(<AuthCallbackPage />);

    expect(screen.getByText("Loading")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        `${API_BASE}/api/auth/google/callback?code=google-code&scope=email&prompt=select_account`,
        { credentials: "include" },
      ),
    );
  });

  it("renders the missing-code failure state without calling the backend", async () => {
    const AuthCallbackPage = await loadAuthCallbackPage();

    render(<AuthCallbackPage />);

    expect(await screen.findByText("로그인 실패")).toBeInTheDocument();
    expect(
      screen.getByText("Google 로그인 code가 없습니다."),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("renders the backend error state when the callback response is not ok", async () => {
    navigationMocks.params = new URLSearchParams({
      code: "google-code",
      scope: "email",
      prompt: "select_account",
    });
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 500 }));
    const AuthCallbackPage = await loadAuthCallbackPage();

    render(<AuthCallbackPage />);

    expect(
      await screen.findByText("인증 처리 중 오류: 백엔드 요청 실패"),
    ).toBeInTheDocument();
  });

  it("renders the known external not-found error state", async () => {
    navigationMocks.params = new URLSearchParams({
      code: "google-code",
      error: "not_found",
    });
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    const AuthCallbackPage = await loadAuthCallbackPage();

    render(<AuthCallbackPage />);

    expect(
      await screen.findByText("등록된 사용자가 아닙니다."),
    ).toBeInTheDocument();
  });

  it("stores the access token, sets the decoded user id, fetches permissions, and redirects on success", async () => {
    navigationMocks.params = new URLSearchParams({
      code: "google-code",
      scope: "email",
      prompt: "select_account",
    });
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          workspace_id: "workspace-1",
          tab_id: "tab-1",
          access_token: "access-token",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const AuthCallbackPage = await loadAuthCallbackPage();

    render(<AuthCallbackPage />);

    await waitFor(() =>
      expect(navigationMocks.replace).toHaveBeenCalledWith(
        "/workspaces/workspace-1/tabs/tab-1",
      ),
    );
    expect(localStorage.getItem("access_token")).toBe("access-token");
    expect(authMocks.jwtDecode).toHaveBeenCalledWith("access-token");
    expect(authMocks.setUserId).toHaveBeenCalledWith("user-1");
    expect(authMocks.fetchPermissions).toHaveBeenCalledWith("workspace-1");
  });
});
