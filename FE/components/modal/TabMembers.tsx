"use client";

import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Users } from "lucide-react";
import { getMemberList, getPossibleMemberList, Member, getTabGroupList, getPossibleGroupList } from "@/apis/tabApi";
import { Group } from "@/apis/groupApi";
import { useEffect, useState } from "react";
import { MemberModal } from "@/components/modal/MemberModal";
import { PossibleGroupsModal } from "@/components/modal/PossibleGroupsModal";
import { useTabInfoStore } from "@/store/tabStore";

export function TabMembers() {
  // 파라미터에서 workspaceId와 tabId 추출
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const tabId = params.tabId as string;

  // 탭 정보 가져오기
  const fetchTabInfo = useTabInfoStore((state) => state.fetchTabInfo);
  const tabInfo = useTabInfoStore((state) => state.tabInfoCache[tabId]);  

  // 메인 멤버 모달 열림 상태 관리
  const [isModalOpen, setIsModalOpen] = useState(false);

  // 메인 멤버 모달 열림 상태 변경 핸들러
  const handleModalOpenChange = (open: boolean) => {
    setIsModalOpen(open);
  };

  // 초대 성공 시 데이터 강제 새로고침
  const onInviteSuccess = () => {
    fetchTabInfo(workspaceId, tabId, { force: true });
  };

  // 멤버 및 그룹 리스트 상태 관리
  const [tabMembers, setTabMembers] = useState<any[]>([]);
  const [tabGroups, setTabGroups] = useState<any[]>([]);

  // 모달 열기 핸들러
  const handleOpenModal = () => {
    if (workspaceId && tabId) {      
      Promise.all([
        getMemberList(workspaceId, tabId),
        getTabGroupList(workspaceId, tabId)
      ]).then(([members, groups]) => {
        setTabMembers(members);
        const formattedGroups = groups.map(group => ({
          ...group,
          group_id: String(group.group_id),
          members_count: group.group_members_count || 0
        }));
        setTabGroups(formattedGroups);
        setIsModalOpen(true); 
      });
    }
  };

  useEffect(() => {
    if (workspaceId && tabId) {
      fetchTabInfo(workspaceId, tabId);
    }
  }, [workspaceId, tabId, tabInfo, isModalOpen]);

  return (
    <>
      {/* 메인 멤버/그룹 모달 */}
      <Button
        variant="ghost"
        size="icon"
        className="flex items-center gap-1 px-7 hover:bg-gray-200 cursor-pointer"
        onClick={handleOpenModal}
      >
        <div className="flex flex-row items-center gap-2">
          <Users className="w-5 h-5 text-gray-800" />
          <span className="text-gray-800 font-bold">
            {tabInfo?.members_count || 0}
          </span>
        </div>
      </Button>

      {isModalOpen && (
        <MemberModal
          workspaceId={workspaceId}
          tabId={tabId}
          title={tabInfo?.tab_name}
          open={isModalOpen}
          onOpenChange={handleModalOpenChange}
          onInviteSuccess={onInviteSuccess}
          membersCount={tabInfo?.members_count || 0}
          tabMembers={tabMembers}
          tabGroups={tabGroups}
          sectionId={tabInfo?.section_id}
        />
      )}
    </>
  );
}
