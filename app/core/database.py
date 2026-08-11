"""
数据库操作模块。
使用MySQL数据库，基于 SQLAlchemy 提供全局数据库实例与会话工厂。

@author: ziyu
@date: 2026-07-17
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings

class Database:
    """MySQL数据库操作类，封装引擎与会话工厂。"""

    def __init__(self):
        self.engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=settings.mysql_pool_recycle,
            echo=settings.mysql_echo,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def get_db(self) -> Session:
        """获取数据库会话（生成器方式，用于 Flask 依赖注入，异常时回滚）。"""
        db = self.SessionLocal()
        try:
            yield db
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

# 全局数据库实例
db = Database()
