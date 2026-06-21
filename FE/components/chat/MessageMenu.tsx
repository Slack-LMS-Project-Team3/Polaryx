"use client";

import { useParams } from "next/navigation";
import { useMyUserStore } from "@/store/myUserStore";
import { Trash2, Pencil, SmilePlus, Pin, Bookmark } from "lucide-react";
import type { MessageId } from "@/store/messageStore";

interface MessageMenuProps {
    msgId: MessageId;
    userId: string;
    content: string;
    onEmoji: () => void;
    onEdit: () => void;
    onDelete: () => void;
    onClose: () => void;
}

export function MessageMenu({ msgId, userId, content, onEmoji, onEdit, onDelete, onClose }: MessageMenuProps) {

    // userId 추출
    const myUserId = useMyUserStore((s) => s.userId);
    
    // URL에서 workspaceId 추출
    const params = useParams();
    const workspaceId = params.workspaceId;
    const tabId = params.tabId;   

    // 메시지 수정
    const handleEdit = () => {
        onEdit();
        onClose();
    };

    const handleEmoji = () => {
        onEmoji();
    };
       
    return (
        <>
            <div className="flex items-center bg-white border border-gray-200 rounded-md shadow-xs p-1 space-x-0">
                <button onClick={handleEmoji} className="px-2 py-1 text-sm rounded-sm hover:bg-gray-200"><SmilePlus className="w-5 h-5 text-gray-600" /></button>
                <button className="px-2 py-1 text-sm rounded-sm hover:bg-gray-200"><Pin className="w-5 h-5 text-gray-600" /></button>
                <button className="px-2 py-1 text-sm rounded-sm hover:bg-gray-200"><Bookmark className="w-5 h-5 text-gray-600" /></button>
                {myUserId === userId && (
                    <>
                        <button onClick={handleEdit} className="px-2 py-1 text-sm rounded-sm hover:bg-gray-200"><Pencil className="w-5 h-5 text-gray-600" /></button>
                        <button onClick={onDelete} className="px-2 py-1 text-sm rounded-sm hover:bg-gray-200 text-red-600"><Trash2 className="w-5 h-5" /></button>
                    </>
                )}
            </div>
        </>
    );
}
