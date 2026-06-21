import { create } from "zustand";

export type EmojiType = 'check' | 'pray' | 'sparkle' | 'clap' | 'like';
export type MessageId = number | string;

export interface PendingEmojiUpdate {
  msgId: MessageId;
  emojiType: EmojiType;
  emojiAction: 'like' | 'unlike';
}

export interface EmojiCounts {
  checkCnt: number;
  prayCnt: number;
  sparkleCnt: number;
  clapCnt: number;
  likeCnt: number;
}

export interface Message {
  tabId?: number;
  senderId: string;
  msgId: MessageId | undefined;
  nickname: string;
  image: string;
  content: string;
  createdAt: string | undefined;
  fileUrl: string | null;
  isUpdated: number;
  checkCnt: number;
  prayCnt: number;
  sparkleCnt: number;
  clapCnt: number;
  likeCnt: number;
  myToggle: Record<string, boolean>;
}

interface MessageStore {
  // 메시지 입력
  message: string;
  setMessage: (msg: string) => void;

  // 수정 버튼 누르면 수정 모드로 변경
  updateMessage: (msgId: MessageId, msg: string) => void;

  // 메시지 삭제
  deleteMessage: (id: MessageId) => void;

  // 메시지 전송 trigger
  sendFlag: boolean;
  editMsgFlag: boolean;
  sendEmojiFlag: boolean;
  sendEditFlag: boolean;
  setSendFlag: (flag: boolean) => void;
  setEditMsgFlag: (msgId: MessageId, newContent:string) => void;
  cleanEditMsgFlag: () => void;
  setSendEmojiFlag: (flag: boolean) => void;
  setSendEditFlag: (flag: boolean) => void;
  
  // 메시지 저장
  messages: Message[];
  setMessages: (msg: Message[]) => void;
  appendMessage: (msg: Message) => void;
  prependMessages: (msg: Message[]) => void;

  // file url 저장
  fileUrl: string | null;
  setFileUrl: (url: string | null) => void;

  updateUserProfile: (
    userId: string,
    updates: { nickname?: string; image?: string },
  ) => void;

  // 새 메시지 실시간 알림
  unreadCounts: Record<number, number>;
  incrementUnread: (tabId: number) => void;
  clearUnread: (tabId: number) => void;

  // 탭 초대 실시간 알림
  invitedTabs: number[];
  addInvitedTab: (tabId: number) => void;
  clearInvitedTab: (tabId: number) => void;

  // EmojiGroup: 이벤트가 발생한 이모지를 배열로 관리
  pendingEmojiUpdates: PendingEmojiUpdate[];  
  addPendingEmojiUpdate: (update: PendingEmojiUpdate) => void;
  clearPendingEmojiUpdates: () => void;

  // 서버 응답을 기다리는 큐
  inFlightEmojiUpdates: PendingEmojiUpdate[];
  addInFlightEmojiUpdates: (updates: PendingEmojiUpdate[]) => void;
  clearInFlightEmojiUpdates: () => void;

  // 웹소켓에서 브로드캐스트된 emoji count를 설정하는 함수
  updateEmojiCounts: (msgId: MessageId, emojiData: EmojiCounts) => void;

  // '좋아요' 버튼 클릭 시 UI가 호출할 단 하나의 함수
  toggleEmoji: () => void;

  // 프로필 수정 시 웹소켓 기능
  editTarget: Record<string, string>;
  editProfile: (editName: string, editImage: string| undefined) => void;

  // 나의 이모지 토글 상태 업데이트 (서버 응답 기다리지 않고 UI 먼저 업데이트)
  toggleMyEmoji: (msgId: MessageId, emojiType: string) => void;

  // 메세지 수정
  editMessage: {
    "msgId": MessageId;
    "content": string;
  }
}

export const useMessageStore = create<MessageStore>((set, get) => ({
  message: "",
  setMessage: (msg) => set({ message: msg }),

  // 수정 버튼 누르면 수정 모드로 변경
  updateMessage: (msgId, msg) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.msgId === msgId ? { ...m, content: msg, isUpdated: 1 } : m,
      ),
    })), // hack : 오류 발생할 수 있음

  // 메시지 삭제
  deleteMessage: (id) =>
    set((state) => ({
      messages: state.messages.filter((msg) => msg.msgId !== id),
    })),

  // 메시지 전송 trigger
  sendFlag: false,
  setSendFlag: (flag) => set({ sendFlag: flag }),

  // List에 메시지 추가
  messages: [],
  setMessages: (msg) => set({ messages: msg }),
  appendMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),
  prependMessages: (msgs) =>
    set((state) => {
      // msgId를 기준으로 중복 제거
      const uniqueMessages = msgs.filter(
        (newMsg) =>
          !state.messages.some(
            (existingMsg) => existingMsg.msgId === newMsg.msgId,
          ),
      );

      return {
        messages: [...uniqueMessages, ...state.messages],
      };
    }),

  // file url 저장
  fileUrl: null,
  setFileUrl: (url) => set({ fileUrl: url }),

  updateUserProfile: (userId, updates) => {
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.senderId === userId
          ? {
              ...msg,
              ...(updates.nickname && { nickname: updates.nickname }),
              ...(updates.image && { image: updates.image }),
            }
          : msg,
      ),
    }));
  },
  // 새 메시지 실시간 알림
  unreadCounts: {},

  incrementUnread: (tabId) =>
    set((state) => ({
      unreadCounts: {
        ...state.unreadCounts,
        [tabId]: (state.unreadCounts[tabId] || 0) + 1,
      },
    })),

  clearUnread: (tabId) =>
    set((state) => ({
      unreadCounts: {
        ...state.unreadCounts,
        [tabId]: 0,
      },
    })),

  // 탭 초대 실시간 알림
  invitedTabs: [],
  addInvitedTab: (tabId) =>
    set((state) => ({
      invitedTabs: state.invitedTabs.includes(tabId)
        ? state.invitedTabs
        : [...state.invitedTabs, tabId],
    })),

  clearInvitedTab: (tabId) =>
    set((state) => ({
      invitedTabs: state.invitedTabs.filter((id) => id !== tabId),
    })),

  // 이벤트가 발생한 이모지를 배열로 관리
  pendingEmojiUpdates: [],
  inFlightEmojiUpdates: [],
  addPendingEmojiUpdate: (update) =>
    set((state) => {
      // 동일 이모지에 대한 중복 업데이트는 마지막 동작만 남깁니다
      const existingIndex = state.pendingEmojiUpdates.findIndex(
        (u) => u.msgId === update.msgId && u.emojiType === update.emojiType,
      );

      if (existingIndex > -1) {
        const newUpdates = [...state.pendingEmojiUpdates];
        newUpdates.splice(existingIndex, 1); // 기존 업데이트 제거
        return { pendingEmojiUpdates: newUpdates };
      }

      return { pendingEmojiUpdates: [...state.pendingEmojiUpdates, update] };
    }),
  clearPendingEmojiUpdates: () => set({ pendingEmojiUpdates: [] }),
  addInFlightEmojiUpdates: (updates) =>
    set((state) => ({
      inFlightEmojiUpdates: [...state.inFlightEmojiUpdates, ...updates],
    })),
  clearInFlightEmojiUpdates: () => set({ inFlightEmojiUpdates: [] }),
  removeFirstInFlightUpdate: (msgId: MessageId) =>
    set((state) => {
      const idx = state.inFlightEmojiUpdates.findIndex(
        (u) => u.msgId === msgId,
      );
      if (idx === -1) return {} as any;
      const newUpdates = [...state.inFlightEmojiUpdates];
      newUpdates.splice(idx, 1);
      return { inFlightEmojiUpdates: newUpdates };
    }),

  sendEmojiFlag: false,
  setSendEmojiFlag: (flag) => set({ sendEmojiFlag: flag }),

  // 서버로부터 받은 최종 이모지 카운트로 업데이트
  updateEmojiCounts: (msgId, emojiData) =>
    set((state) => {
      // 전달받은 업데이트가 처리한 in-flight 작업을 제거합니다.
      const idx = state.inFlightEmojiUpdates.findIndex(
        (u) => u.msgId === msgId,
      );
      const remainingInFlight = [...state.inFlightEmojiUpdates];
      if (idx > -1) {
        remainingInFlight.splice(idx, 1);
      }

      // 해당 메시지에 추가로 대기 중인 작업이 있다면 서버 값을 적용하지 않고 대기합니다.
      const hasMorePending = remainingInFlight.some((u) => u.msgId === msgId);
      if (hasMorePending) {
        return { inFlightEmojiUpdates: remainingInFlight };
      }

      return {
        messages: state.messages.map((msg) =>
          msg.msgId === msgId
            ? {
                ...msg,
                checkCnt: emojiData.checkCnt,
                prayCnt: emojiData.prayCnt,
                sparkleCnt: emojiData.sparkleCnt,
                clapCnt: emojiData.clapCnt,
                likeCnt: emojiData.likeCnt,
              }
            : msg,
        ),
        inFlightEmojiUpdates: remainingInFlight,
      };
    }),

  // 이모지 버튼 선택 시 동작할 함수
  toggleEmoji: () => {
    set((state) => ({
      sendEmojiFlag: true, // 이모지 전송 플래그 설정
    }));
  },

  // Edit Profile 기능
  sendEditFlag: false,
  setSendEditFlag: (flag) => set({ sendEditFlag: flag }),

  editTarget: {"":""},
  editProfile: (editName, editImage) => {
    set((state) => ({
      editTarget:{
        "nickname": editName,
        "image": editImage ? editImage:"none"
      },
      sendEditFlag: true
    }));
  },

  // 나의 이모지 토글 상태 업데이트
  toggleMyEmoji: (msgId, emojiType) =>
    set((state) => ({
      messages: state.messages.map((msg) => {
        if (msg.msgId === msgId) {
          const newMyToggle = { ...msg.myToggle };
          const isToggled = newMyToggle[emojiType];
          newMyToggle[emojiType] = !isToggled;

          const currentCount = msg[`${emojiType}Cnt` as keyof Message] as number;
          const newCount = newMyToggle[emojiType] ? currentCount + 1 : Math.max(0, currentCount - 1);

          return { ...msg, myToggle: newMyToggle, [`${emojiType}Cnt`]: newCount };
        }
        return msg;
      }),
    })),

  // 메세지 수정 기능
  editMsgFlag: false,
  editMessage: {
    "msgId": 0,
    "content": ""
  },
  setEditMsgFlag: (msgId, content) => {
    set((state) => ({
      editMessage:{
        "msgId": msgId,
        "content": content
      },
      editMsgFlag: true
    }));
  },

  cleanEditMsgFlag: () => {
    set((state) => ({
      editMessage:{
        "msgId": 0,
        "content": ""
      },
      editMsgFlag: false
    }));
  },


}));
