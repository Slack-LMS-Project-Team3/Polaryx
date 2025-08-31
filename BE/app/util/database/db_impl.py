from abc import ABCMeta
from mysql.connector import pooling
from app.config.config import settings 

class ConnectionError(Exception):
    pass


class ExecuteError(Exception):
    pass



pool = pooling.MySQLConnectionPool(
    pool_name           = "mypool",
    pool_size           = 20,
    host                = settings.RDB_HOST,
    port                = int(settings.RDB_PORT),
    user                = settings.DB_USER,
    password            = settings.DB_PASSWORD,
    database            = settings.DB_NAME,
    connection_timeout  = int(settings.CONNECTION_TIMEOUT),
    autocommit          = True,
    charset             = "utf8mb4"
)


class DBImpl(metaclass = ABCMeta):
    def __init__(self):
        self.pool = pool
        # self.connection = pool.get_connection()
        # self.cursor = self.connection.cursor()