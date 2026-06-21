import { MiniProfile } from "./MiniProfile";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { deleteMessage } from "@/apis/messageApi";
import { toast } from "sonner";
import { Ban } from "lucide-react";
import { ImageWithModal } from "./imageWithModal";
import { HoverCard, HoverCardTrigger } from "@/components/ui/hover-card";
import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu";
import { FileDownload } from "@/components/chat/fileUpload/FileUpload";
import DOMPurify from "dompurify";
import ChatEditTiptap from "./ChatEditTiptap";
import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import { updateMessage as updateMessageApi } from "@/apis/messageApi";
import { useMessageStore, type MessageId } from "@/store/messageStore";
import { useProfileStore } from "@/store/profileStore";
import { cn } from "@/lib/utils";
import { SmilePlus } from "lucide-react";
import { jwtDecode } from "jwt-decode";
import { MessageMenu } from "./MessageMenu";
import { EmojiGroupMenu, EmojiGroup } from "./EmojiGroup";

interface ChatProfileProps {
  senderId: string;
  msgId: MessageId;
  imgSrc: string;
  nickname: string;
  time: string;
  content: string;
  showProfile: boolean;
  fileUrl: string | null;
  isUpdated: number;
  className?: string;
  checkCnt: number;
  prayCnt: number;
  sparkleCnt: number;
  clapCnt: number;
  likeCnt: number;
  myToggle: Record<string, boolean>;
  isEditMode: boolean;
  onStartEdit: () => void;
  onEndEdit: () => void;
}

function isImageFile(url: string) {
  return /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(url);
}

function isPersistedMessageId(msgId: MessageId): msgId is number {
  return typeof msgId === "number" && Number.isFinite(msgId) && msgId > 0;
}

export function ChatProfile({
  senderId,
  msgId,
  imgSrc,
  nickname,
  time,
  content,
  showProfile,
  fileUrl,
  isUpdated,
  className,
  checkCnt,
  prayCnt,
  sparkleCnt,
  clapCnt,
  likeCnt,
  myToggle,
  isEditMode,
  onStartEdit,
  onEndEdit,
}: ChatProfileProps) {
  // 프로필
  const openProfile = useProfileStore((s) => s.openWithId);
  const removeMessage = useMessageStore((s) => s.deleteMessage);

  const safeHTML = DOMPurify.sanitize(content, {
    FORBID_TAGS: ["img"], // 👈 img 태그 완전 제거
  });
  // const [isEditMode, setIsEditMode] = useState(false); // 부모로부터 받으므로 이 줄은 삭제합니다.
  const [editContent, setEditContent] = useState(content);
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const tabId = params.tabId as string;
  const { setEditMsgFlag } = useMessageStore();

  // 메시지 저장 핸들러
  const handleSave = async (newContent: string) => {
    if (!isPersistedMessageId(msgId)) {
      toast.error("저장 중인 메시지는 아직 수정할 수 없습니다");
      return;
    }

    setEditContent(newContent);
    onEndEdit(); // props로 받은 함수를 호출하여 수정 모드를 종료합니다.
    try {
      await updateMessageApi(workspaceId, tabId, msgId, newContent); // 서버에 PATCH
      setEditMsgFlag(msgId, newContent); // broadcast
    } catch (e) {
      alert("메시지 수정 실패");
    }
  };

  // 메시지 호버 상태 관리(메시지 메뉴 표시)
  const [isHovered, setIsHovered] = useState(false);

  // 메시지 삭제 확인 모달 상태 관리
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

  // 이모지 메뉴 표시 상태 관리
  const [isEmojiGroupOpen, setIsEmojiGroupOpen] = useState(false);

  // 메시지 삭제 핸들러
  const handleDelete = async (id: number) => {
    try {
      // API 호출
      await deleteMessage(workspaceId as string, tabId as string, id);
      // 로컬 store 에서 메시지 제거
      removeMessage(id);
    } catch (e) {
      toast.error("메시지 삭제에 실패했습니다", {
        icon: <Ban className="size-5" />,
      });
    }
  };

  const handleDeleteMessage = async () => {
    if (!isPersistedMessageId(msgId)) {
      toast.error("저장 중인 메시지는 아직 삭제할 수 없습니다");
      return;
    }

    await handleDelete(msgId);
  };

  const closeMenu = () => {
    setIsHovered(false);
  };

  // 메시지 삭제 확인 모달 열기
  const openDeleteDialog = () => {
    setIsDeleteDialogOpen(true);
    setIsHovered(false); // 메뉴를 닫는 로직을 이 함수에 통합
  };

  // 편집 취소 핸들러
  const handleCancel = () => {
    onEndEdit(); // props로 받은 함수를 호출하여 수정 모드를 종료합니다.
  };

  // 이모지 메뉴 열기
  const openEmojiGroup = () => {
    setIsEmojiGroupOpen(true);
  };

  // 이모지 메뉴 닫기
  const closeEmojiGroup = () => {
    setIsEmojiGroupOpen(false);
  };

  // 마우스가 메시지 영역을 떠났을 때 이모지 그룹 메뉴 닫기
  const handleMouseLeave = () => {
    setIsHovered(false);
    setIsDeleteDialogOpen(false);
    setIsEmojiGroupOpen(false);
  };

  return (
    <div
      onMouseEnter={() => {
        if (!isDeleteDialogOpen) {
          setIsHovered(true);
        }
      }}
      onMouseLeave={handleMouseLeave}
      className={cn(
        `relative flex px-[8px] py-[4.5px] group${isEditMode ? " bg-blue-50" : " hover:bg-gray-200"}`,
        className,
      )}
    >
      {/* showProfile(마지막 메세지로부터 5분 이후)이면, 프로필 사진, 이름, 메시지 표시. 아니면 메시지만 */}
      {showProfile ? (
        <div className="relative">
          <HoverCard>
            <HoverCardTrigger asChild>
              <button
                onClick={() => openProfile(senderId)}
                className="w-[40px] mr-[8px] cursor-pointer ml-4.5"
              >
                <img
                  src={imgSrc}
                  className="w-[40px] h-[40px] mt-1 rounded-lg object-cover bg-gray-400"
                  alt="profile"
                />
              </button>
            </HoverCardTrigger>
            <MiniProfile
              senderId={senderId}
              imgSrc={imgSrc}
              nickname={nickname}
            />
          </HoverCard>
        </div>
      ) : (
        <div className="flex flex-shrink-0 items-center justify-end text-xxs ml-4.5 chat-time-stamp w-[40px] mr-[8px]">
          <div className="hidden group-hover:block">{time.split(" ")[1]}</div>
        </div>
      )}

      <div className="w-full m-[-12px 8px -16px -16px] p-[8px 8px 8px 16px]">
        {isEditMode ? (
          <>
            {showProfile && (
              <div className="flex items-baseline space-x-1 mb-1"></div>
            )}
            <ChatEditTiptap
              initialContent={editContent}
              onSave={handleSave}
              onCancel={handleCancel}
            />
          </>
        ) : (
          <>
            {showProfile && (
              <div className="flex items-baseline space-x-1">
                <HoverCard>
                  <HoverCardTrigger asChild>
                    <span
                      onClick={() => openProfile(senderId)}
                      className="text-m-bold cursor-pointer hover:underline"
                    >
                      {nickname}
                    </span>
                  </HoverCardTrigger>
                  <MiniProfile
                    senderId={senderId}
                    imgSrc={imgSrc}
                    nickname={nickname}
                  />
                </HoverCard>

                <span className="text-xs chat-time-stamp">{time}</span>
              </div>
            )}

            <div className="flex flex-wrap flex-row items-center message-content whitespace-pre-wrap break-words break-anywhere text-m">
              <div
                className="mr-2"
                dangerouslySetInnerHTML={{ __html: safeHTML }}
              />
              {isUpdated ? (
                <span
                  className="text-xs text-gray-500"
                  style={{ whiteSpace: "nowrap" }}
                >
                  (편집됨)
                </span>
              ) : null}
            </div>
            {fileUrl && isImageFile(fileUrl) && (
              <ImageWithModal fileUrl={fileUrl} />
            )}

            {fileUrl && !isImageFile(fileUrl) && (
              <div className="mt-2">
                <FileDownload fileUrl={fileUrl} />
              </div>
            )}
            <EmojiGroup
              msgId={msgId}
              onClose={closeEmojiGroup}
              userId={senderId}
              checkCnt={checkCnt}
              clapCnt={clapCnt}
              prayCnt={prayCnt}
              sparkleCnt={sparkleCnt}
              likeCnt={likeCnt}
              myToggle={myToggle}
            />
          </>
        )}
      </div>
      {!isEditMode && isHovered && !isDeleteDialogOpen && !isEmojiGroupOpen && (
        <div className="absolute -top-5 right-2">
          <MessageMenu
            msgId={msgId}
            userId={senderId}
            content={editContent}
            onEmoji={openEmojiGroup}
            onEdit={onStartEdit}
            onDelete={openDeleteDialog}
            onClose={closeMenu}
          />
        </div>
      )}
      {isHovered && isEmojiGroupOpen && (
        <div className="absolute -top-5 right-2">
          <EmojiGroupMenu
            msgId={msgId}
            userId={senderId}
            onClose={closeEmojiGroup}
            checkCnt={checkCnt}
            clapCnt={clapCnt}
            prayCnt={prayCnt}
            sparkleCnt={sparkleCnt}
            likeCnt={likeCnt}
            myToggle={myToggle}
          />
        </div>
      )}
      <AlertDialog
        open={isDeleteDialogOpen}
        onOpenChange={setIsDeleteDialogOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>메시지 삭제</AlertDialogTitle>
            <AlertDialogDescription>
              메시지를 삭제하시겠습니까? 이 작업은 실행 취소할 수 없습니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setIsDeleteDialogOpen(false)}>
              취소
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteMessage}>
              삭제
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
