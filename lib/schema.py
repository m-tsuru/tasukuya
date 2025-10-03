from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True)
    user_name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return super().__repr__()


class Guild(Base):
    __tablename__ = "guilds"
    guild_id = Column(String, primary_key=True)
    guild_name = Column(String)
    create_user = Column(String, ForeignKey("users.user_id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return super().__repr__()


class TaskList(Base):
    __tablename__ = "tasklists"
    id = Column(String, primary_key=True)
    guild_id = Column(String, ForeignKey("guilds.guild_id"))
    prefix = Column(String)

    def __repr__(self) -> str:
        return super().__repr__()


class Task(Base):
    __tablename__ = "tasks"
    task_id = Column(String, primary_key=True)
    task_name = Column(String)
    due_date = Column(DateTime(timezone=True))
    done_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return super().__repr__()


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.task_id"))
    user_id = Column(String, ForeignKey("users.user_id"))

    def __repr__(self) -> str:
        return super().__repr__()


class WebSession(Base):
    __tablename__ = "web_sessions"
    id = Column(String, primary_key=True)
    guild_id = Column(String, ForeignKey("guilds.guild_id"))
    session_key = Column(String)
    expired_at = Column(
        DateTime(timezone=True),
        server_default=func.now() + func.interval("1 hour"),
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return super().__repr__()
