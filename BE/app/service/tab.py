from typing import List
from app.repository.tab import TabRepository
from fastapi import HTTPException
from app.schema.tab.response import TabMember

# 탭 퇴장시 시스템 메세지를 위한 websocket_manager
from app.service.websocket_manager import ConnectionManager
from app.service.message import MessageService
from uuid import UUID

connection = ConnectionManager()
message_service = MessageService()

class TabService:
    DEFAULT_TAB_IDS: tuple[int, ...] = tuple(range(1, 15))
    
    def __init__(self):
        self.repo = TabRepository()

    def is_tab_name_duplicate(self, workspace_id: int, section_id:int, name: str):
        return self.repo.is_duplicate(workspace_id, section_id, name)

    def create_tab(self, user_ids: List, workspace_id: int, tab_name: str, section_id: int):
        is_valid = self.repo.validate_section_in_workspace(section_id, workspace_id)
        if not is_valid:
            raise HTTPException(status_code=400, detail="섹션이 이 워크스페이스에 속하지 않습니다.")
        self.insert_tab(workspace_id, tab_name, section_id)
        rows = self.find_by_unique_key(workspace_id, tab_name, section_id)
        tab_id = rows[0][0]
        self.invite_members(workspace_id, tab_id, user_ids)
        return rows[0]

    def insert_tab(self, workspace_id: int, tab_name: str, section_id: int):
        return self.repo.insert(workspace_id, tab_name, section_id)

    def find_tabs(self, workspace_id: int, user_id):
        return self.repo.find_all(workspace_id, user_id)
        
    def find_tab(self, workspace_id: int, tab_id: int):
        return self.repo.find(workspace_id, tab_id)
    
    def find_by_unique_key(self, workspace_id: int, tab_name: str, section_id: int):
        return self.repo.find_by_uq(workspace_id, tab_name, section_id)

    def get_tab_members(self, workspace_id: int, tab_id: int): 
        return self.repo.find_members(workspace_id, tab_id)

    def get_available_tab_members(self, workspace_id: int, tab_id: int):
        return self.repo.find_non_members(workspace_id, tab_id)

    def get_tab_groups(self, workspace_id: int, tab_id: int):
        return self.repo.find_tab_groups(workspace_id, tab_id)

    def get_available_groups(self, workspace_id: int, tab_id: int):
        return self.repo.find_available_groups(workspace_id, tab_id)
    
    def invite_groups(self, workspace_id: int, tab_id: int, group_ids: List[str], user_id: str):
        return self.repo.insert_group_members(workspace_id, tab_id, group_ids, user_id)
    
    def invite_members(self, workspace_id: int, tab_id: int, user_ids: List[str]):
        row = self.repo.insert_members(workspace_id, tab_id, user_ids)
        
        tab_info = self.find_tab(workspace_id, tab_id)
        section_id = tab_info[0][2]
        if section_id == 4: # dm에 인원 초대 시 tab_name 변경
            member_names = []
            for member in row: 
                member_names.append(member[0])
                tab_name = ", ".join(member_names)
            self.modify_name(workspace_id, tab_id, tab_name)

        return row
    
    def add_member_to_default_tabs(self, workspace_id: int, user_id: str) -> int:
        self.repo.insert_member_to_tabs(workspace_id, self.DEFAULT_TAB_IDS, user_id)

    async def exit_tab(self, workspace_id: int, tab_id: int, user_ids: List[str]):
        users = self.repo.exit_members(workspace_id, tab_id, user_ids)
        users.sort()

        # 탭 정보 조회 (섹션 ID 확인용)
        tab_info = self.find_tab(workspace_id, tab_id)
        section_id = tab_info[0][2] if tab_info else None

        for user in users:
            print("in exit_tab, user_names: ", user[0])
            # [0]: nickname, [1]: user_id, [2]: tab_name
            
            # DM 섹션(section_id == 4)인 경우 메시지 형태 변경
            if section_id == 4:
                exit_message = f"<p style='color: gray'>{user[0]}님이 나갔습니다.</p>"
            else:
                exit_message = f"<p style='color: gray'>{user[0]}님이 {user[2]}에서 나갔습니다.</p>"

            await connection.broadcast(workspace_id, tab_id, exit_message)
            await message_service.save_message(tab_id,
                                               UUID(user[1]),
                                               exit_message,
                                               None)

        # 탭에 남은 멤버가 없는 경우 탭 삭제
        remaining_count = self.repo.check_tab_has_members(tab_id)
        if remaining_count == 0:
            self.repo.delete_tab(workspace_id, tab_id)

        return len(users)
    
    def modify_name(self, workspace_id: int, tab_id: int, tab_name: str):
        self.repo.update_tab_name(workspace_id, tab_id, tab_name)