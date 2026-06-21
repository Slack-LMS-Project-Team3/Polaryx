import { beforeEach, describe, expect, it, vi } from "vitest";
import { getUserPermissions } from "@/apis/roleApi";
import { useMyPermissionsStore } from "../myPermissionsStore";
import { useMyUserStore } from "../myUserStore";

vi.mock("@/apis/roleApi", () => ({
  getUserPermissions: vi.fn(),
}));

const getUserPermissionsMock = vi.mocked(getUserPermissions);

describe("useMyPermissionsStore", () => {
  beforeEach(() => {
    useMyPermissionsStore.setState({ workspacePermissions: {} });
    useMyUserStore.setState({ userId: null });
    getUserPermissionsMock.mockReset();
  });

  it("sets workspace permissions and checks individual permission membership", () => {
    useMyPermissionsStore
      .getState()
      .setWorkspacePermissions("workspace-1", ["TAB_READ", "TAB_WRITE"]);

    expect(
      useMyPermissionsStore
        .getState()
        .hasPermission("workspace-1", "TAB_READ"),
    ).toBe(true);
    expect(
      useMyPermissionsStore
        .getState()
        .hasPermission("workspace-1", "ADMIN"),
    ).toBe(false);
  });

  it("stores fetched permissions for the current user", async () => {
    useMyUserStore.setState({ userId: "user-1" });
    getUserPermissionsMock.mockResolvedValue(["TAB_READ"]);

    await useMyPermissionsStore.getState().fetchPermissions("workspace-1");

    expect(getUserPermissionsMock).toHaveBeenCalledWith(
      "workspace-1",
      "user-1",
    );
    expect(useMyPermissionsStore.getState().workspacePermissions).toEqual({
      "workspace-1": ["TAB_READ"],
    });
  });

  it("skips fetching when workspace permissions are already cached", async () => {
    useMyUserStore.setState({ userId: "user-1" });
    useMyPermissionsStore.setState({
      workspacePermissions: { "workspace-1": ["TAB_READ"] },
    });

    await useMyPermissionsStore.getState().fetchPermissions("workspace-1");

    expect(getUserPermissionsMock).not.toHaveBeenCalled();
  });

  it("does nothing when there is no current user id", async () => {
    await useMyPermissionsStore.getState().fetchPermissions("workspace-1");

    expect(getUserPermissionsMock).not.toHaveBeenCalled();
    expect(useMyPermissionsStore.getState().workspacePermissions).toEqual({});
  });

  it("falls back to an empty permission list when fetching fails", async () => {
    useMyUserStore.setState({ userId: "user-1" });
    getUserPermissionsMock.mockRejectedValue(new Error("request failed"));

    await useMyPermissionsStore.getState().fetchPermissions("workspace-1");

    expect(useMyPermissionsStore.getState().workspacePermissions).toEqual({
      "workspace-1": [],
    });
  });
});
