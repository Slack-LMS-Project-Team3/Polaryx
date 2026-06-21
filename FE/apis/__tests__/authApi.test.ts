import { beforeEach, describe, expect, it, vi } from "vitest";

const API_BASE = "https://api.example.test";

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

async function loadAuthApi() {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_BASE", API_BASE);
  return import("../authApi");
}

function getHeadersFromFetchCall(callIndex: number): Headers {
  const init = vi.mocked(fetch).mock.calls[callIndex]?.[1] as RequestInit;
  return new Headers(init.headers);
}

describe("fetchWithAuth", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", createMemoryStorage());
    window.history.replaceState({}, "", "/auth/callback");
    vi.stubGlobal("fetch", vi.fn());
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("returns null and does not call fetch when access_token is absent", async () => {
    const { fetchWithAuth } = await loadAuthApi();
    const fetchMock = vi.mocked(fetch);

    await expect(fetchWithAuth(`${API_BASE}/api/tabs`)).resolves.toBeNull();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("adds bearer authorization and credentials while preserving caller headers", async () => {
    const { fetchWithAuth } = await loadAuthApi();
    const fetchMock = vi.mocked(fetch);
    const response = new Response("{}", { status: 200 });
    fetchMock.mockResolvedValue(response);
    localStorage.setItem("access_token", "existing-token");

    await expect(
      fetchWithAuth(`${API_BASE}/api/tabs`, {
        method: "GET",
        headers: new Headers({
          Accept: "application/json",
        }),
      }),
    ).resolves.toBe(response);

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/tabs`,
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      }),
    );
    const headers = getHeadersFromFetchCall(0);
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer existing-token");
  });

  it("refreshes an expired token, stores the replacement, and retries the request", async () => {
    const { fetchWithAuth } = await loadAuthApi();
    const fetchMock = vi.mocked(fetch);
    const expiredResponse = new Response(
      JSON.stringify({ message: "EXPIRED TOKEN" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
    const refreshResponse = new Response(
      JSON.stringify({ access_token: "new-token" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
    const retryResponse = new Response("{}", { status: 200 });
    fetchMock
      .mockResolvedValueOnce(expiredResponse)
      .mockResolvedValueOnce(refreshResponse)
      .mockResolvedValueOnce(retryResponse);
    localStorage.setItem("access_token", "expired-token");

    await expect(fetchWithAuth(`${API_BASE}/api/tabs`)).resolves.toBe(
      retryResponse,
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${API_BASE}/api/auth/refresh`,
      {
        method: "POST",
        credentials: "include",
      },
    );
    expect(localStorage.getItem("access_token")).toBe("new-token");
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${API_BASE}/api/tabs`,
      expect.objectContaining({
        credentials: "include",
      }),
    );
    expect(getHeadersFromFetchCall(2).get("Authorization")).toBe(
      "Bearer new-token",
    );
  });

  it("returns null when token refresh succeeds without a replacement token", async () => {
    const { fetchWithAuth } = await loadAuthApi();
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ message: "EXPIRED TOKEN" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    localStorage.setItem("access_token", "expired-token");

    await expect(fetchWithAuth(`${API_BASE}/api/tabs`)).resolves.toBeNull();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("returns null and redirects home when the access token is invalid", async () => {
    const authApi = await loadAuthApi();
    const redirectHome = vi
      .spyOn(authApi.authRedirect, "home")
      .mockImplementation(() => {});
    const { fetchWithAuth } = authApi;
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "INVALID ACCESS TOKEN" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    localStorage.setItem("access_token", "invalid-token");

    await expect(fetchWithAuth(`${API_BASE}/api/tabs`)).resolves.toBeNull();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(redirectHome).toHaveBeenCalledOnce();
  });
});
