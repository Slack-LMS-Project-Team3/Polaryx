"use client";

import { Member, Group } from "@/apis/tabApi";
import { ReactNode, useState, useEffect } from "react";
import { TabMembersModal } from "./TabMembersModal";
import { TabGroupsModal } from "./TabGroupsModal";
import { PossibleMembersModal } from "./PossibleMembersModal";
import { PossibleGroupsModal } from "./PossibleGroupsModal";
import { getPossibleMemberList, getPossibleGroupList } from "@/apis/tabApi";
import { ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";

interface MemberModalProps {
  workspaceId: string;
  tabId: string;
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInviteSuccess: () => void;
  membersCount: number;
  tabMembers: Member[];
  tabGroups: Group[];
  sectionId: number;
}

export function MemberModal({
  workspaceId,
  tabId,
  title,
  open,
  onOpenChange,
  onInviteSuccess,
  membersCount,
  tabMembers,
  tabGroups,
  sectionId,
}: MemberModalProps) {
  const [view, setView] = useState<"members" | "groups" | "add-members" | "add-groups">("members");

  const [possibleMembers, setPossibleMembers] = useState<Member[]>([]);
  const [possibleGroups, setPossibleGroups] = useState<Group[]>([]);

  const handleAddMembersClick = () => {
    getPossibleMemberList(workspaceId, tabId).then(setPossibleMembers);
    setView("add-members");
  };

  const handleAddGroupsClick = () => {
    getPossibleGroupList(workspaceId, tabId).then(setPossibleGroups);
    setView("add-groups");
  };

  const handleBack = () => {
    if (view === "add-members") setView("members");
    if (view === "add-groups") setView("groups");
  };  

  const renderTitle = () => {
    switch (view) {
      case "members":
      case "groups":
        return title;
      case "add-members":
        return "Add Members";
      case "add-groups":
        return "Add Groups";
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="p-0 pt-2 gap-0 w-[30vw] max-w-md h-3/4 flex flex-col">
        <DialogHeader className={`p-4 flex flex-row items-center flex-none ${
          view != "members" && view != "groups" ? "border-b-[1px] border-gray-400 shadow-sm" : ""
        }`}>
          {(view === "add-members" || view === "add-groups") && (
            <Button onClick={handleBack} variant="ghost" size="icon" className="mr-2">
              <ChevronLeft />
            </Button>
          )}
          <DialogTitle className="text-xl font-bold">{renderTitle()}</DialogTitle>
        </DialogHeader>

        {(view === "members" || view === "groups") && (
          <div className="flex-none">
            <Tabs value={view} onValueChange={(value) => setView(value as any)} className="w-full border-b-[1px] border-gray-400 shadow-sm">
              <TabsList>
                <TabsTrigger value="members">
                  Members ({membersCount})
                </TabsTrigger>
                {sectionId !== 4 && (
                  <TabsTrigger value="groups">
                    Groups ({tabGroups.length})
                  </TabsTrigger>
                )}
              </TabsList>
            </Tabs>
          </div>
        )}
        <Separator/>
        <div className="flex-grow overflow-y-auto scrollbar-thin">
          {view === "members" && (
            <TabMembersModal tabMembers={tabMembers} onAddClick={handleAddMembersClick} sectionId={sectionId} />
          )}
          {view === "groups" && (
            <TabGroupsModal tabGroups={tabGroups} onAddClick={handleAddGroupsClick} />
          )}
          {view === "add-members" && (
            <PossibleMembersModal
              workspaceId={workspaceId}
              tabId={tabId}
              possibleMembers={possibleMembers}
              onBack={handleBack}
              onInviteComplete={() => {
                onOpenChange(false);
                onInviteSuccess();
              }}
            />
          )}
          {view === "add-groups" && (
            <PossibleGroupsModal
              workspaceId={workspaceId}
              tabId={tabId}
              possibleGroups={possibleGroups}
              onBack={handleBack}
              onInviteComplete={() => {
                onOpenChange(false);
                onInviteSuccess();
              }}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
