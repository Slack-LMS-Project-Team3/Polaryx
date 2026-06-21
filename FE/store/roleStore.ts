import { create } from 'zustand';
import { Role } from '@/apis/roleApi';
import { getRoles } from '@/apis/roleApi';


interface RoleState {
  roles: Record<string, Role[]>; // key: workspaceId, value: roles
  refreshTrigger: Record<string, number>;
  
  fetchRoles: (workspaceId: string, forceRefresh?: boolean) => Promise<Role[]>;
  triggerRefresh: (workspaceId: string) => void;
}

export const useRoleStore = create<RoleState>((set, get) => ({
  roles: {},
  refreshTrigger: {},
  
  fetchRoles: async (workspaceId: string, forceRefresh: boolean = false) => {
    try {
      // 이미 데이터가 있는지 확인 (강제 새로고침이 아닌 경우에만)
      const currentRoles = get().roles[workspaceId];
      if (!forceRefresh && currentRoles && currentRoles.length > 0) {
        return currentRoles; // 강제 새로고침이 아니고 이미 데이터가 있으면 그대로 반환
      }
      
      const roles = await getRoles(workspaceId);
      console.log('역할 API 응답 데이터:', roles);
      
      // user_names, group_name, permissions 필드가 없는 경우 빈 배열로 초기화하고 DM 권한 추가
      const processedRoles = roles.map(role => {
        const permissions = role.permissions || [];
                
        return {
          ...role,
          user_names: role.user_names || [],
          group_names: role.group_names || [],
          permissions: permissions
        };
      });    
      
      // 상태 업데이트
      set((state) => ({
        roles: {
          ...state.roles,
          [workspaceId]: processedRoles,
        },
      }));
      
      return processedRoles;
    } catch (error) {
      console.error('역할 데이터 가져오기 오류:', error);
      return [];
    }
  },
  
  triggerRefresh: (workspaceId: string) => {
    set((state) => ({
      refreshTrigger: {
        ...state.refreshTrigger,
        [workspaceId]: (state.refreshTrigger[workspaceId] || 0) + 1
      }
    }));
    
    // 해당 워크스페이스의 데이터 강제로 다시 불러오기
    get().fetchRoles(workspaceId, true);
  }
}));
