import os
import sqlparse
from app.util.database.abstract_query_repo import AbstractQueryRepo
from app.util.database.db_factory import DBFactory


class DBRepository(AbstractQueryRepo):
    def __init__(self):
        db = DBFactory.get_db("MySQL")
        super().__init__(db)
    
    def reset(self):
        """
        데이터베이스를 초기화하는 함수
        1. 기존 테이블들 드롭
        2. CREATE 쿼리 실행
        3. INSERT 쿼리 실행 (seed 데이터)
        """
        try:
            # 1. 기존 테이블들 드롭
            self._drop_all_tables()
            
            # 2. CREATE 쿼리 실행
            self._execute_create_queries()
            
            # 3. INSERT 쿼리 실행 (seed 데이터가 있다면)
            self._execute_insert_queries()
            
            print("데이터베이스 초기화가 완료되었습니다.")
            
        except Exception as e:
            print(f"데이터베이스 초기화 중 오류 발생: {e}")
            raise
    
    def _drop_all_tables(self):
        """모든 테이블을 드롭하는 함수"""
        # 외래키 제약조건을 무시하고 테이블 드롭
        drop_queries = [
            "SET FOREIGN_KEY_CHECKS = 0;",
            "DROP TABLE IF EXISTS `canvases`;", 
            "DROP TABLE IF EXISTS `emoji`;",
            "DROP TABLE IF EXISTS `group_members`;",
            "DROP TABLE IF EXISTS `groups`;",
            "DROP TABLE IF EXISTS `links`;",
            "DROP TABLE IF EXISTS `member_roles`;",
            "DROP TABLE IF EXISTS `messages`;",
            "DROP TABLE IF EXISTS `notifications`;",
            "DROP TABLE IF EXISTS `push_subscriptions`;",
            "DROP TABLE IF EXISTS `refresh_tokens`;",
            "DROP TABLE IF EXISTS `roles`;",
            "DROP TABLE IF EXISTS `save_messages`;",
            "DROP TABLE IF EXISTS `sections`;",
            "DROP TABLE IF EXISTS `tab_members`;",
            "DROP TABLE IF EXISTS `tabs`;",
            "DROP TABLE IF EXISTS `users`;",
            "DROP TABLE IF EXISTS `workspace_members`;",
            "DROP TABLE IF EXISTS `workspaces`;"
        ]
        
        for query in drop_queries:
            self.execute(query)
    
    def _execute_create_queries(self):
        """CREATE 쿼리들을 실행하는 함수"""
        create_sql_path = os.path.join(os.path.dirname(__file__), '../../sql/init/ddl_create_tables.sql')
        
        with open(create_sql_path, 'r', encoding='utf-8') as file:
            sql_content = file.read()

        # 더 정확한 SQL 분리
        queries = []
        current_query = ""
        
        for line in sql_content.split('\n'):
            line = line.strip()
            if line and not line.startswith('--'):  # 주석 제외
                current_query += line + " "
                if line.endswith(';'):
                    queries.append(current_query.strip())
                    current_query = ""

        for query in queries:
            if query.strip():
                print(f"Executing: {query[:100]}...")  # 디버깅용
                self.execute(query)
    
    def _execute_insert_queries(self):
        """INSERT 쿼리들을 실행하는 함수 (seed 데이터)"""
        insert_sql_path = os.path.join(os.path.dirname(__file__), '../../sql/seed/dml_insert_seed.sql')
        with open(insert_sql_path, 'r', encoding='utf-8') as file:
            sql_content = file.read()

        # (선택) 주석 제거
        cleaned = sqlparse.format(sql_content, strip_comments=True)

        # 안전하게 쿼리별로 분리
        statements = sqlparse.split(cleaned)

        for stmt in statements:
            stmt = stmt.strip()
            print("stmt", stmt)
            if stmt:
                self.execute(stmt)
