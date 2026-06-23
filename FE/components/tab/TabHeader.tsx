"use client";

import { useEffect } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import {
  ChartColumn,
  Link,
  LogOut,
  MessageCircle,
  StickyNote,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTabInfoStore } from "@/store/tabStore";
import { TabMembers } from "@/components/modal/TabMembers";
import { ExitTab } from "@/components/chat/ExitTab"

export function TabHeader() {
  // URL에서 workspaceId와 tabId 추출
  const params = useParams();
  const router = useRouter();
  const pathname = usePathname();
  const workspaceId = params.workspaceId as string;
  const tabId = params.tabId as string;

  // 탭 정보 가져오기
  const fetchTabInfo = useTabInfoStore((state) => state.fetchTabInfo);
  const tabInfo = useTabInfoStore((state) => state.tabInfoCache[tabId]);

  useEffect(() => {
    if (workspaceId && tabId) {
      fetchTabInfo(workspaceId, tabId);
    }
  }, [workspaceId, tabId, fetchTabInfo]);

  // 현재 활성화된 탭 확인 (message, canvas, link, report)
  const getCurrentTab = () => {
    if (pathname.includes("/canvases")) return "canvas";
    if (pathname.includes("/links")) return "links";
    if (pathname.includes("/report")) return "report";
    return "messages";
  };

  // 탭 선택 시 라우팅 핸들러
  const handleTabChange = (value: string) => {
    let path = "";
    switch (value) {
      case "canvas":
        path = `/workspaces/${workspaceId}/tabs/${tabId}/canvases/231bae03622f80679bfcfc9b96a0ff03`;
        break;
      case "links":
        path = `/workspaces/${workspaceId}/tabs/${tabId}/links`;
        break;
      case "report":
        path = `/workspaces/${workspaceId}/tabs/${tabId}/report`;
        break;
      default:
        path = `/workspaces/${workspaceId}/tabs/${tabId}`;
        break;
    }
    router.push(path);
  };

  return (
    <div className="sticky top-0 bg-white border-b-[1px] border-gray-400 shadow-sm">
      <div className="flex items-center h-[50px] px-[17px]">
        <div className="flex flex-1 justify-between items-center h-[30px] px-[3px]">
          <div className="flex items-center">
            {tabInfo?.tab_name ? (
              <p className="text-lg font-semibold">{tabInfo.tab_name}</p>
            ) : (
              <div className="w-40 h-7 rounded-md bg-gray-300 animate-pulse" />
            )}
          </div>

          <div className="flex flex-row items-center gap-2">
            <TabMembers />
            <ExitTab />
          </div>
        </div>
      </div>
      <Tabs value={getCurrentTab()} onValueChange={handleTabChange}>
        <TabsList>
          {tabInfo?.section_id === 2 && (
            <TabsTrigger value="canvas">
              <StickyNote />
              <p>Canvas</p>
            </TabsTrigger>
          )}
          <TabsTrigger value="messages">
            <MessageCircle />
            <p>Message</p>
          </TabsTrigger>
          <TabsTrigger value="links">
            <Link />
            <p>Link</p>
          </TabsTrigger>
          {tabInfo?.section_id === 2 && (
            <TabsTrigger value="report">
              <ChartColumn />
              <p>Report</p>
            </TabsTrigger>
          )}
        </TabsList>
      </Tabs>
    </div>
  );
}
