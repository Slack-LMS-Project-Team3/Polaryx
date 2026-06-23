import { fetchWithAuth } from "./authApi";
import { Group, InviteGroups } from "./groupApi";
export type { Group, InviteGroups };

const BASE = process.env.NEXT_PUBLIC_BASE;

export interface Tab {
  tab_id: number;
  tab_name: string;
  section_id: number;
  section_name?: string;
  members_count?: number | null;
  members?: Member[] | null;
}

export interface Member {
  user_id: string;
  nickname: string;
  image?: string | null;
  role_id?: number;
  role_name?: string;
  group_id?: number[] | [];
  group_name?: string[] | [];
}

/* 탭 이름 중복 확인 */
export async function checkTabName(
  workspaceId: string,
  sectionId: string,
  tabName: string,
): Promise<boolean> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/sections/${sectionId}/tabs?name=${tabName}`,
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );
  if (res == null || !res.ok) throw new Error("탭 이름 중복 확인 실패");
  return res.json();
}

/* 탭 정보(이름, 인원 수) 조회 */
export async function getTabInfo(
  workspaceId: string,
  tabId: string,
): Promise<Tab> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/info`,
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (res == null || !res.ok) throw new Error("탭 정보 조회 실패");
  return res.json();
}

/* 탭 리스트 조회 */
export async function getTabList(workspaceId: string): Promise<Tab[]> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/tabs`,
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (res == null || !res.ok) throw new Error("탭 리스트 조회 실패");
  return res.json();
}

/* 탭 추가 (섹션 타입, 탭 이름, 참여자 id 필요) */
export async function createTab(
  workspaceId: string,
  sectionId: string,
  tabName: string,
): Promise<Tab> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/tabs`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        workspace_id: workspaceId,
        section_id: sectionId,
        tab_name: tabName,
      }),
    },
  );

  if (res == null || !res.ok) throw new Error("탭 추가 실패");
  return res.json();
}

/* 탭 참여 인원 조회 */
export async function getMemberList(
  workspaceId: string,
  tabId: string,
): Promise<Member[]> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/members`,
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );
  if (res == null) return [];
  if (!res.ok) throw new Error("탭 참여 인원 조회 실패");
  return res.json();
}

/* 탭 참여 가능 인원 조회 */
export async function getPossibleMemberList(
  workspaceId: string,
  tabId: string,
): Promise<Member[]> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/non-members`,
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    },
  );
  if (res == null) return [];
  if (!res.ok) throw new Error("탭 참여 가능 인원 조회 실패");
  return res.json();
}

/* 탭 인원 초대 */
export async function postMemberList(
  workspaceId: string,
  tabId: string,
  userIds: string[],
): Promise<Member[]> {
  const res = await fetchWithAuth(
    `${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/members`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ user_ids: userIds }),
    },
  );
  if (res == null || !res.ok) throw new Error("탭 참여 인원 추가 실패");
  return res.json();
}

/* 탭 참여 그룹 조회 */
export async function getTabGroupList(workspaceId: string, tabId: string): Promise<Group[]> {
  const res = await fetchWithAuth(`${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/groups`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
    },
  );
  if (res == null || !res.ok) throw new Error("탭 참여 그룹 조회 실패");
  return res.json();
}

/* 탭 참여 가능 그룹 조회 */
export async function getPossibleGroupList(workspaceId: string, tabId: string): Promise<Group[]> {
  const res = await fetchWithAuth(`${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/non-groups`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
    },
  );
  if (res == null || !res.ok) throw new Error("탭 참여 가능 그룹 조회 실패");
  return res.json();
}

/* 탭 그룹 초대 */
export async function postGroupList(workspaceId: string, tabId: string, groupIds: string[]): Promise<InviteGroups> {
  const res = await fetchWithAuth(`${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/groups`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ group_ids: groupIds }),
    },
  );
  if (res == null || !res.ok) throw new Error("탭 그룹 추가 실패");
  return res.json();
}

/* 탭 나가기 */
 export async function exitTab(workspaceId: string, tabId: string, userIds: string[]): Promise<boolean> {
    const res = await fetchWithAuth(`${BASE}/api/workspaces/${workspaceId}/tabs/${tabId}/out`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: userIds }),
      },
    );
    if (res == null || !res.ok) throw new Error("탭 나가기 실패");
    return true;
  }