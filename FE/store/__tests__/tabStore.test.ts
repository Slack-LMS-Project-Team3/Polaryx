import { beforeEach, describe, expect, it, vi } from "vitest";
import { getTabInfo } from "@/apis/tabApi";
import { useTabInfoStore, useTabStore } from "../tabStore";

vi.mock("@/apis/tabApi", () => ({
  getTabInfo: vi.fn(),
}));

const getTabInfoMock = vi.mocked(getTabInfo);

describe("useTabStore", () => {
  beforeEach(() => {
    useTabStore.setState({ needsRefresh: false });
  });

  it("sets and resets the sidebar refresh flag", () => {
    useTabStore.getState().refreshTabs();
    expect(useTabStore.getState().needsRefresh).toBe(true);

    useTabStore.getState().resetRefresh();
    expect(useTabStore.getState().needsRefresh).toBe(false);
  });
});

describe("useTabInfoStore", () => {
  beforeEach(() => {
    useTabInfoStore.setState({ tabInfoCache: {}, loadingTabs: {} });
    getTabInfoMock.mockReset();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("tracks loading state and caches fetched tab info", async () => {
    let resolveInfo!: (value: Awaited<ReturnType<typeof getTabInfo>>) => void;
    getTabInfoMock.mockReturnValue(
      new Promise((resolve) => {
        resolveInfo = resolve;
      }),
    );

    const fetchPromise = useTabInfoStore
      .getState()
      .fetchTabInfo("workspace-1", "tab-1");

    expect(useTabInfoStore.getState().loadingTabs["tab-1"]).toBe(true);

    resolveInfo({ tab_id: 1, tab_name: "general" });
    await fetchPromise;

    expect(getTabInfoMock).toHaveBeenCalledWith("workspace-1", "tab-1");
    expect(useTabInfoStore.getState().tabInfoCache["tab-1"]).toEqual({
      tab_id: 1,
      tab_name: "general",
    });
    expect(useTabInfoStore.getState().loadingTabs["tab-1"]).toBe(false);
  });

  it("skips cached tab info unless force refetch is requested", async () => {
    useTabInfoStore.setState({
      tabInfoCache: { "tab-1": { tab_id: 1, tab_name: "cached" } },
      loadingTabs: {},
    });

    await useTabInfoStore.getState().fetchTabInfo("workspace-1", "tab-1");

    expect(getTabInfoMock).not.toHaveBeenCalled();

    getTabInfoMock.mockResolvedValue({ tab_id: 1, tab_name: "fresh" });
    await useTabInfoStore
      .getState()
      .fetchTabInfo("workspace-1", "tab-1", { force: true });

    expect(getTabInfoMock).toHaveBeenCalledWith("workspace-1", "tab-1");
    expect(useTabInfoStore.getState().tabInfoCache["tab-1"].tab_name).toBe(
      "fresh",
    );
  });

  it("does not duplicate a fetch while a tab is already loading", async () => {
    useTabInfoStore.setState({
      tabInfoCache: {},
      loadingTabs: { "tab-1": true },
    });

    await useTabInfoStore.getState().fetchTabInfo("workspace-1", "tab-1");

    expect(getTabInfoMock).not.toHaveBeenCalled();
  });

  it("clears loading state when the API request fails", async () => {
    getTabInfoMock.mockRejectedValue(new Error("network down"));

    await useTabInfoStore.getState().fetchTabInfo("workspace-1", "tab-1");

    expect(useTabInfoStore.getState().tabInfoCache).toEqual({});
    expect(useTabInfoStore.getState().loadingTabs["tab-1"]).toBe(false);
  });
});
