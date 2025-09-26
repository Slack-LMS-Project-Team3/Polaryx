"use client";

import { ReactNode } from "react";
import { Separator } from "@/components/ui/separator";
import {
  SidebarProvider,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar";
import { MemberModal } from "./MemberModal";
import { InviteListItem } from "@/components/tab/InviteListItem";
import { UserRoundPlus } from "lucide-react";
import { Member } from "@/apis/tabApi";

export interface TabMembersModalProps {
  tabMembers: Member[];
  onAddClick?: () => void;
  sectionId: number;
}

export function TabMembersModal({
  tabMembers,
  onAddClick,
  sectionId,
}: TabMembersModalProps) {
  return (
    <div className="flex flex-col overflow-y-auto scrollbar-thin gap-0">
      <SidebarProvider>
        <SidebarMenu>
          {onAddClick && sectionId !== 4 && (
            <InviteListItem
              key="add-member-button"
              user={{ nickname: "Add Members" }}
              mode="addMember"
              onClick={onAddClick}
            />
          )}
          {tabMembers.map((member) => (
            <InviteListItem
              key={member.user_id}
              user={member}
              mode="tabMember"
            />
          ))}
        </SidebarMenu>
      </SidebarProvider>
    </div>
  );
}
