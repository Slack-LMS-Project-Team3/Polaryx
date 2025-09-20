from typing import List
import logging
from app.repository.role import QueryRepo as RolesRepo
from app.domain.role import Role
from app.core.exceptions import (
    ResourceNotFoundError,
    ResourceConflictError,
    DatabaseError
)

from uuid import UUID

class RoleService:
    def __init__(self):
        self.repo = RolesRepo()

    def insert_member_roles_bulk(self, data: dict):
        # 1. 모든 role 정보 가져오기 (role_id, role_name)
        roles_data = self.repo.get_all_roles()  # [(1, 'Admin'), (2, 'Guest'), ...]
        
        # 2. role_name -> role_id 매핑 딕셔너리 생성
        role_name_to_id = {role_name: role_id for role_id, role_name in roles_data}
        
        # 3. bulk insert용 데이터 리스트 생성
        member_roles_list = []
        for user_data in data["users"]:
            email = user_data["email"]
            name = user_data["name"] 
            # role_name = user_data["role"]
            role_name = "Guest"
            
            # role_name으로 role_id 찾기
            if role_name in role_name_to_id:
                role_id = role_name_to_id[role_name]
                member_roles_list.append({
                    "email": email,
                    "role_id": role_id,
                    "name": name
                })
            else:
                print(f"Unknown role: {role_name} for user: {email}")
        
        return self.repo.bulk_insert_member_roles(member_roles_list)

    def insert_member_roles(self, data: dict):
        # 1. 모든 role 정보 가져오기 (role_id, role_name)
        roles_data = self.repo.get_all_roles()  # [(1, 'Admin'), (2, 'Guest'), ...]
        
        # 2. role_name -> role_id 매핑 딕셔너리 생성
        role_name_to_id = {role_name: role_id for role_id, role_name in roles_data}
        
        # 3. 
        role_name = data.get("role_name")
        
        # role_name으로 role_id 찾기
        if role_name in role_name_to_id:
            role_id = role_name_to_id[role_name]
            params = {
                "user_id": data["user_id"],
                "user_name": data["user_name"],
                "role_id": role_id
            }
        self.repo.insert_member_roles(params)
    
    def find_all(self, workspace_id: int) -> List[Role]:
        try:
            rows = self.repo.find_all(workspace_id)
            return [Role.from_row(row) for row in rows]
        except Exception as e:
            logging.error(f"역할 목록 조회 서비스 오류 - workspace_id: {workspace_id}, error: {e}")
            raise DatabaseError("역할 목록을 조회하는 중 오류가 발생했습니다")

    def find(self, workspace_id: int, user_id: UUID.bytes) -> Role:
        try:
            row = self.repo.find_by_user_id(workspace_id, user_id)
            return Role.from_row(row)
        except ValueError as e:
            raise ResourceNotFoundError(f"역할을 찾을 수 없습니다 - user_id: {user_id}")
        except Exception as e:
            logging.error(f"역할 조회 서비스 오류 - user_id: {user_id}, workspace_id: {workspace_id}, error: {e}")
            raise DatabaseError("역할을 조회하는 중 오류가 발생했습니다")
    
    def create(self, workspace_id: int, role_name: str, permissions: List) -> Role:        
        try:
            self.repo.insert(workspace_id, role_name, permissions)
            row = self.repo.find_by_name(workspace_id, role_name)
            return Role.from_row(row)
        except ValueError as e:
            if "이미 존재합니다" in str(e):
                raise ResourceConflictError(f"같은 이름의 역할이 이미 존재합니다 - role_name: {role_name}")
            else:
                raise ResourceNotFoundError(str(e))
        except Exception as e:
            logging.error(f"역할 생성 서비스 오류 - role_name: {role_name}, workspace_id: {workspace_id}, error: {e}")
            raise DatabaseError("역할을 생성하는 중 오류가 발생했습니다")

    def modify(self, workspace_id: int, role_id: int, role_name: str, permissions: List) -> Role:
        try:
            self.repo.update(workspace_id, role_id, role_name, permissions)
            row = self.repo.find(workspace_id, role_id)
            return Role.from_row(row)
        except ValueError as e:
            raise ResourceNotFoundError(f"수정할 역할을 찾을 수 없습니다 - role_id: {role_id}")
        except Exception as e:
            logging.error(f"역할 수정 서비스 오류 - role_id: {role_id}, workspace_id: {workspace_id}, error: {e}")
            raise DatabaseError("역할을 수정하는 중 오류가 발생했습니다")

    def delete(self, workspace_id: int, role_id: int) -> None:
        try:
            return self.repo.delete(workspace_id, role_id)
        except ValueError as e:
            raise ResourceNotFoundError(f"삭제할 역할을 찾을 수 없습니다 - role_id: {role_id}")
        except Exception as e:
            logging.error(f"역할 삭제 서비스 오류 - role_id: {role_id}, workspace_id: {workspace_id}, error: {e}")
            raise DatabaseError("역할을 삭제하는 중 오류가 발생했습니다")

    # 미완
    def delete_member_roles(self, user_id: str, workspace_id: int) -> bool:
        result = self.repo.delete_mem_role(UUID(user_id).bytes, workspace_id)
        return result