"use client";

import { useMyUserStore } from "@/store/myUserStore";
import { useRouter, useParams } from "next/navigation";
import { useState } from "react";
import { useTabStore } from "@/store/tabStore"
import { LogOut, Ban } from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTrigger,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { exitTab, getTabList } from "@/apis/tabApi";

export function ExitTab () {
  const router = useRouter();

  // 현재 사용자 정보 가져오기
  const userId = useMyUserStore((state) => state.userId);

  // 탭 상태 가져오기
  const { refreshTabs } = useTabStore();

  // 현재 워크스페이스/탭 정보 가져오기
  const { workspaceId, tabId } = useParams();

  // 모달 열림 상태 관리
  const [isOpen, setIsOpen] = useState(false);

  // 삭제 처리 로딩 상태
  const [isLoading, setIsLoading] = useState(false);

  // 탭 나가기 후 이동할 탭 아이디 추출
  const getNextAvailableTab = async (workspaceId: string) => {
    const tabs = await getTabList(workspaceId);

    const sortedTabs = tabs.sort((a, b) => {
      if (a.section_id !== b.section_id) {
        return a.section_id - b.section_id;
      }
      return a.tab_id - b.tab_id;
    });

    return sortedTabs[0] || null;
  };

  // 탭 나가기 동작
  const handleConfirmExit = async () => {
    if (!userId) return;

    try {
      setIsLoading(true);
      await exitTab(workspaceId as string, tabId as string, [userId]);

      refreshTabs();

      const nextTab = await getNextAvailableTab(workspaceId as string);
      if (nextTab) {
        router.push(`/workspaces/${workspaceId}/tabs/${nextTab.tab_id}`);
      } else {
        router.push(`/workspaces/${workspaceId}`);
      }
    } catch (error) {
      toast.error("탭을 나가지 못했습니다", {
        icon: <Ban className="size-5" />,
      });
    } finally {
      setIsLoading(false);
      setIsOpen(false);
    }
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={setIsOpen}>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="flex items-center gap-1 px-7 hover:bg-gray-200"
        >
          <LogOut size={28} />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>탭에서 나가시겠습니까?</AlertDialogTitle>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirmExit} disabled={isLoading}>
            {isLoading ? "나가는 중..." : "나가기"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};







