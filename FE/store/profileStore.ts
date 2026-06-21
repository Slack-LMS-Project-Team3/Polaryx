"use client";

import { create } from "zustand";
import { Profile } from "@/apis/profileApi";
import { get } from "http";
import { profile } from "console";

interface ProfileStore {
  isOpen: boolean;
  userId: string | null;
  profile: Profile | null;
  setProfile: (prof: Profile) => void;
  updateProfile: (targetId: string, name: string, image?: string) => void;
  setUserId: (id: string) => void;
  setOpen: () => void;
  setClose: () => void;
  openWithId: (id: string) => void;
}

export const useProfileStore = create<ProfileStore>((set) => ({
  isOpen: false,
  userId: null,
  profile: null,
  setProfile: (prof) => set({ profile: prof }),
  updateProfile: (targetId, name, image) =>
    set((state) => {
      if (!state.profile || targetId != state.userId) return {}; // 아무 것도 안 함
      return {
        profile: {
          ...state.profile,
          nickname: name,
          image: image ?? state.profile.image,
        },
      };
    }),  
  setUserId: (id) => set({ userId: id }),
  setOpen: () => set({ isOpen: true }),
  setClose: () => set({ isOpen: false }),
  openWithId: (id) => set({ userId: id, isOpen: true }),
}));
