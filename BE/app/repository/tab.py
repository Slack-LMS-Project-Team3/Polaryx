from app.util.database.abstract_query_repo import AbstractQueryRepo
from app.util.database.db_factory import DBFactory
from uuid import UUID
from typing import List, Optional
from datetime import datetime

is_dup_name_in_tab_by_section = """
SELECT * FROM tabs
WHERE 
      workspace_id = %(workspace_id)s
  AND section_id = %(section_id)s
  AND name = %(name)s;
"""

create_tab = """
INSERT INTO tabs (
    name, 
    workspace_id, 
    section_id
)
VALUES (
    %(tab_name)s, 
    %(workspace_id)s, 
    %(section_id)s
)
"""

find_tab_by_uq = """
SELECT id, name, section_id
FROM tabs
WHERE workspace_id = %(workspace_id)s
  AND name = %(tab_name)s
  AND section_id = %(section_id)s
"""

find_tab = """
SELECT
  t.id,
  t.name,
  t.section_id,
  s.name
FROM tab_members tm
LEFT JOIN tabs t ON t.id = tm.tab_id
LEFT JOIN sections s 
  ON s.id = t.section_id 
 AND s.workspace_id = t.workspace_id
WHERE t.workspace_id = %(workspace_id)s
  AND t.id = %(tab_id)s
  AND t.deleted_at IS NULL;
"""

find_tabs = """
SELECT DISTINCT
  t.id,
  t.name,
  t.section_id,
  s.name
FROM tabs t
LEFT JOIN tab_members tm ON t.id = tm.tab_id
LEFT JOIN sections s 
  ON s.id = t.section_id 
 AND s.workspace_id = t.workspace_id
WHERE tm.workspace_id = %(workspace_id)s
  AND tm.user_id = %(user_id)s
  AND t.deleted_at IS NULL;
"""

is_section_in_workspace = """
SELECT * FROM sections
WHERE 
      id = %(section_id)s #
  AND workspace_id = %(workspace_id)s;
"""

find_members = """
SELECT 
    wm.user_id,
    wm.nickname,
    wm.image, 
    MAX(r.name) AS role,
    GROUP_CONCAT(DISTINCT g.name) AS `groups`
FROM workspace_members wm
LEFT JOIN tab_members tm
  ON wm.user_id = tm.user_id
 AND tm.workspace_id = wm.workspace_id
LEFT JOIN member_roles mr ON wm.user_id = mr.user_id
LEFT JOIN roles r ON mr.role_id = r.id
LEFT JOIN group_members gm ON wm.user_id = gm.user_id
LEFT JOIN `groups` g ON gm.group_id = g.id
WHERE wm.workspace_id = %(workspace_id)s
  AND tm.workspace_id = %(workspace_id)s
  AND tm.tab_id = %(tab_id)s
  AND wm.deleted_at IS NULL
GROUP BY wm.user_id, wm.nickname, wm.image;
"""

find_non_members = """
SELECT 
    wm.user_id,
    wm.nickname,
    wm.image, 
    r.name as role,
    GROUP_CONCAT(DISTINCT g.name) as `groups`
FROM workspace_members wm
LEFT JOIN member_roles mr ON wm.user_id = mr.user_id
LEFT JOIN roles r ON mr.role_id = r.id
LEFT JOIN group_members gm ON wm.user_id = gm.user_id
LEFT JOIN `groups` g ON gm.group_id = g.id
WHERE wm.workspace_id = %(workspace_id)s
  AND wm.user_id NOT IN (
      SELECT user_id
      FROM tab_members
      WHERE workspace_id = %(workspace_id)s
        AND tab_id = %(tab_id)s
  )
  AND wm.deleted_at IS NULL
GROUP BY wm.user_id, wm.nickname, wm.image, r.name;
"""

find_tab_groups = """
SELECT
  g.id, g.name
FROM
  group_members gm
LEFT JOIN tab_members tm
  ON gm.user_id = tm.user_id AND tm.tab_id = %(tab_id)s
JOIN `groups` g ON g.id = gm.group_id
GROUP BY
  gm.group_id
HAVING
  COUNT(DISTINCT gm.user_id) = COUNT(DISTINCT tm.user_id);
"""

find_available_groups = """
SELECT
  g.id, g.name
FROM
  group_members gm
LEFT JOIN tab_members tm
  ON gm.user_id = tm.user_id AND tm.tab_id = %(tab_id)s
JOIN `groups` g ON g.id = gm.group_id
GROUP BY
  gm.group_id
HAVING
  COUNT(DISTINCT gm.user_id) > COUNT(DISTINCT tm.user_id);
"""

find_groups_role_name = """
SELECT
  r.name
FROM
  roles r
JOIN member_roles mr ON r.id = mr.role_id
JOIN group_members gm ON mr.user_id = gm.user_id
WHERE gm.group_id = %(group_id)s;
"""

count_group_members = """
SELECT COUNT(*) FROM group_members
WHERE group_id = %(group_id)s;
"""

insert_tab = """
INSERT INTO tabs (name, workspace_id, section_id)
VALUES (%(tab_name)s, %(workspace_id)s, %(section_id)s);
"""

insert_tab_members = """
INSERT INTO tab_members (workspace_id, user_id, tab_id, user_name)
SELECT %(workspace_id)s, %(user_id)s, %(tab_id)s, wm.nickname
FROM workspace_members wm
WHERE wm.user_id = %(user_id)s AND wm.workspace_id = %(workspace_id)s;
"""

insert_tab_group_members = """
INSERT INTO tab_members (workspace_id, tab_id, user_id, user_name)
SELECT
  %(workspace_id)s AS workspace_id,
  %(tab_id)s AS tab_id,
  gm.user_id,
  gm.user_name
FROM
  group_members gm
LEFT JOIN tab_members tm
  ON tm.workspace_id = %(workspace_id)s
  AND tm.tab_id = %(tab_id)s
  AND tm.user_id = gm.user_id
WHERE
  gm.group_id = %(group_id)s
  AND tm.id IS NULL;
"""

find_group_name_by_id = """
SELECT name FROM `groups`
WHERE id = %(group_id)s
  AND deleted_at IS NULL;
"""

insert_first_message = """
INSERT INTO messages (tab_id, sender_id, content, sender_name, workspace_id)
SELECT
  %(tab_id)s AS tab_id,
  %(user_id)s AS sender_id,
  %(content)s AS content,  
  wm.nickname As sender_name,
  %(workspace_id)s AS workspace_id
FROM
  workspace_members wm
WHERE
  wm.user_id = %(user_id)s
  AND deleted_at IS NULL;
"""

exit_tab_members_by_id = """
DELETE FROM tab_members 
WHERE id =%(id)s;
"""

find_exit_member_by_user_id = """
SELECT wm.nickname, tm.id, t.name FROM tab_members tm
JOIN workspace_members wm ON tm.user_id = wm.user_id
JOIN tabs t ON tm.tab_id = t.id
WHERE tm.user_id = %(user_id)s
  AND tm.tab_id = %(tab_id)s
  AND wm.deleted_at IS NULL
  AND t.deleted_at IS NULL;
"""

find_nicknames = """
SELECT wm.nickname 
FROM tab_members tm 
JOIN workspace_members wm 
  ON wm.user_id = tm.user_id 
WHERE tm.tab_id = %(tab_id)s;
"""

find_tabs_by_id = """
SELECT * FROM tabs WHERE id = %(id)s;
"""

find_tab_member_by_user_id = """
SELECT * FROM tab_members WHERE user_id = %(user_id)s;
"""

update_tab_name = """
UPDATE tabs SET name = %(tab_name)s,
                updated_at = %(updated_at)s
WHERE workspace_id = %(workspace_id)s
  AND id = %(tab_id)s;
"""

delete_empty_tab = """
UPDATE tabs SET deleted_at = %(deleted_at)s
WHERE workspace_id = %(workspace_id)s
  AND id = %(tab_id)s
  AND deleted_at IS NULL;
"""

check_tab_has_members = """
SELECT COUNT(*) FROM tab_members
WHERE tab_id = %(tab_id)s;
"""

class TabRepository(AbstractQueryRepo):
    def __init__(self):
        db = DBFactory.get_db("MySQL")
        super().__init__(db)

    def is_duplicate(self, workspace_id: int, section_id:int, name: str):
        param = {
            "workspace_id": workspace_id,
            "section_id": section_id,
            "name": name
        }
        result = self.execute(is_dup_name_in_tab_by_section, param)
        return bool(result)

    def insert(self, workspace_id, tab_name, section_id):
        param = {
            "workspace_id": workspace_id,
            "tab_name": tab_name,
            "section_id": section_id
        }
        self.execute(insert_tab, param)

    def find(self, workspace_id: int, tab_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id
        }
        return self.execute(find_tab, param)

    def find_by_uq(self, workspace_id: int, tab_name: str, section_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_name": tab_name,
            "section_id": section_id
        }
        return self.execute(find_tab_by_uq, param)
    
    def find_tabs_by_id(self, tab_id: int):
        param = {
            "id": tab_id
        }
        return self.execute(find_tabs_by_id, param)
    
    def find_all(self, workspace_id: int, user_id: str):
        param = {
            "workspace_id": workspace_id,
            "user_id": UUID(user_id).bytes
        }
        return self.execute(find_tabs, param)
    
    def validate_section_in_workspace(self, section_id: int, workspace_id: int):
        param = {
            "workspace_id": workspace_id,
            "section_id": section_id
        }
        result = self.execute(is_section_in_workspace, param)
        return bool(result)

    def find_members(self, workspace_id: int, tab_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id
        }
        return self.execute(find_members, param)

    def find_non_members(self, workspace_id: int, tab_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id
        }
        return self.execute(find_non_members, param)
    
    def find_tab_groups(self, workspace_id: int, tab_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id
        }
        res = self.execute(find_tab_groups, param)
        for i in range(0, len(res)):
            res[i] = list(res[i])
            group_id = {"group_id":res[i][0]}
            res_role_names = self.execute(find_groups_role_name, group_id)
            role_names = []
            for role_name in res_role_names:
                role_names.append(role_name[0])
            if len(set(role_names)) == 1:
                res[i].append(role_names[0])
            else:
                res[i].append("MIXED")
            count = self.execute(count_group_members, group_id)
            res[i].append(count[0][0])
        return res
    
    def find_available_groups(self, workspace_id: int, tab_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id
        }
        res = self.execute(find_available_groups, param)
        for i in range(0, len(res)):
            res[i] = list(res[i])
            group_id = {"group_id":res[i][0]}
            res_role_names = self.execute(find_groups_role_name, group_id)
            role_names = []
            for role_name in res_role_names:
                role_names.append(role_name[0])
            if len(set(role_names)) == 1:
                res[i].append(role_names[0])
            else:
                res[i].append("MIXED")
            count = self.execute(count_group_members, group_id)
            res[i].append(count[0][0])
        return res
    
    # 미완
    def insert_group_members(self, workspace_id: int, tab_id: int, group_ids: List[str], user_id: str):
        res = 0
        group_names = []
        for group_id in group_ids:
          params = {
              "workspace_id": workspace_id,
              "tab_id": tab_id,
              "group_id": int(group_id)
          }
          r = self.execute(insert_tab_group_members, params)
          # group 이름 찾아와서 반환하고,
          g_name_data = self.execute(find_group_name_by_id, params)
          group_names.append(g_name_data[0][0])
          res += r["rowcount"]

        return [res, group_names]

    def insert_members(self, workspace_id: int, tab_id: int, user_ids: List[str]):
        for user_id in user_ids:
            param = {
                "workspace_id": workspace_id,
                "tab_id": tab_id,
                "user_id": UUID(user_id).bytes
            }
            self.execute(insert_tab_members, param)
        return self.execute(find_nicknames, {"tab_id": tab_id})    
    
    def exit_members(self, workspace_id: int, tab_id: int, user_ids: List[str]):
        res = []
        for user_id in user_ids:
            param = {
                "workspace_id": workspace_id,
                "tab_id": tab_id,
                "user_id": UUID(user_id).bytes
            }
            target = self.execute(find_exit_member_by_user_id, param)
            # [0]: nickname, [1]: id, [2]: tab_name
            res.append((target[0][0], user_id, target[0][2]))
            target_id = {"id": target[0][1]}
            self.execute(exit_tab_members_by_id, target_id)
        return res
    
    def find_by_user_id(self, user_id: UUID.bytes):
        param = {
            "user_id": user_id
        }
        return self.db.execute(find_tab_member_by_user_id, param)
    
    def update_tab_name(self, workspace_id: int, tab_id: int, tab_name: str):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id,
            "tab_name": tab_name,
            "updated_at": datetime.now()
        }
        self.db.execute(update_tab_name, param)
    
    def insert_member_to_tabs(self, workspace_id: int, tab_ids: tuple[int], user_id: str):
        for tab_id in tab_ids:
            param = {
                "workspace_id": workspace_id,
                "tab_id": tab_id,
                "user_id": user_id
            }
            self.db.execute(insert_tab_members, param)

    def check_tab_has_members(self, tab_id: int) -> int:
        param = {"tab_id": tab_id}
        result = self.execute(check_tab_has_members, param)
        return result[0][0] if result else 0

    def delete_tab(self, workspace_id: int, tab_id: int):
        param = {
            "workspace_id": workspace_id,
            "tab_id": tab_id,
            "deleted_at": datetime.now()
        }
        self.execute(delete_empty_tab, param)
