"use client";

import LinkTable from "@/components/link/linkTable";
import AddLinkButton from "@/components/link/addLinkButton";
import { useParams } from "next/navigation";
import { useState } from "react";

export default function Page() {
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const tabId = params.tabId as string;
  const [reload, setReload] = useState(0);

  return (
    <div className="px-30 py-8 bg-muted w-full h-full min-h-0 flex flex-col overflow-y-auto scrollbar-thin">
      <div className="flex w-full flex-row items-center justify-between mb-5 pl-4">
        <div className="text-xl text-foreground">링크</div>
        <AddLinkButton
          workspaceId={workspaceId}
          tabId={tabId}
          onCreated={() => setReload((r) => r + 1)}
        />
      </div>
      <div className="flex-1 h-full">
        <LinkTable workspaceId={workspaceId} tabId={tabId} reload={reload} />
      </div>
    </div>
  );
}
