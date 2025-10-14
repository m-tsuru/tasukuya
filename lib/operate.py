import datetime
from zoneinfo import ZoneInfo

from discord import Member as DiscordMember, User as DiscordUser
from sqlalchemy import and_
from sqlalchemy.orm import Session

from lib.schema import Guild, Task, TaskAssignee, TaskList, User


class TasukuyaError(Exception):
    def __str__(self) -> str:
        return "An Unexpected Error occurred in Tasukuya."


class InvalidTaskIDError(Exception):
    def __init__(self, value: str) -> None:
        msg = f"Invalid task ID: the suffix after '-' in '{value}' is not a digit."
        super().__init__(msg)


def parse_task_id(task_id_like_strings: str) -> tuple[int | None, str]:
    if "-" in task_id_like_strings:
        results = task_id_like_strings.rsplit("-", 1)
    else:
        results = (None, task_id_like_strings)
    if len(results) == 0:
        msg = "Invalid task ID: input is empty"
        raise ValueError(msg)
    if not results[-1].isdigit():
        msg = f"Invalid task ID: the suffix after '-' in '{task_id_like_strings}' is not a digit."  # noqa: E501
        raise InvalidTaskIDError(task_id_like_strings)
    return results


def parse_date(
    like_date_strings: str | None,
    tz: ZoneInfo | None = None,
) -> datetime.datetime:
    if tz is None:
        tz = ZoneInfo("Asia/Tokyo")
    now = datetime.datetime.now(tz=tz)
    if like_date_strings is None:
        return now + datetime.timedelta(weeks=1)
    if len(like_date_strings) == 4:  # noqa: PLR2004
        dt_partial = datetime.datetime.strptime(like_date_strings, "%m%d")  # noqa: DTZ007
        dt = datetime.datetime(
            year=now.year,
            month=dt_partial.month,
            day=dt_partial.day,
            hour=now.hour,
            minute=now.minute,
            second=now.second,
            tzinfo=tz,
        )
    elif len(like_date_strings) == 8:  # noqa: PLR2004
        dt_partial = datetime.datetime.strptime(like_date_strings, "%Y%m%d")  # noqa: DTZ007
        dt = datetime.datetime(
            year=dt_partial.year,
            month=dt_partial.month,
            day=dt_partial.day,
            hour=now.hour,
            minute=now.minute,
            second=now.second,
            tzinfo=tz,
        )
    elif len(like_date_strings) == 12:  # noqa: PLR2004
        dt_partial = datetime.datetime.strptime(like_date_strings, "%Y%m%d%H%M")  # noqa: DTZ007
        dt = datetime.datetime(
            year=dt_partial.year,
            month=dt_partial.month,
            day=dt_partial.day,
            hour=dt_partial.hour,
            minute=dt_partial.minute,
            second=0,
            tzinfo=tz,
        )
    else:
        msg = "Invalid Date Format"
        raise ValueError(msg)
    return dt


def create_user_if_not_exists(db: Session, user_id: str, user_name: str) -> User:
    """
    If the user ID is not registered, create a new one;
    if it exists, return it as is.
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        user = User(user_id=user_id, user_name=user_name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def create_guild(
    db: Session,
    guild_id: str,
    guild_name: str,
    create_user_id: str,
) -> Guild:
    """
    If the Guild ID is not registered, create a new one;
    if it exists, return it as is.
    """
    guild = db.query(Guild).filter(Guild.guild_id == guild_id).first()
    if guild is None:
        guild = Guild(
            guild_id=guild_id,
            guild_name=guild_name,
            create_user=create_user_id,
        )
        db.add(guild)
        db.commit()
        db.refresh(guild)
    return guild


def get_tasklist(
    db: Session,
    guild_id: str,
    prefix: str | None,
) -> tuple[int, str] | tuple[None, None]:
    """
    Retrieve the task list ID and prefix from the Guild ID.

    If a prefix is specified, it returns the task list with the matching prefix from the
    task lists associated with the guild ID. If no matching items are found,
    it returns None.

    If prefix is None, it will retrieve the default task list. If no matching items are
    found, it returns None.
    """
    if prefix is None:
        tasklist = (
            db.query(TaskList)
            .filter(
                TaskList.guild_id == guild_id,
                TaskList.default.is_(True),
            )
            .first()
        )
    else:
        tasklist = (
            db.query(TaskList)
            .filter(
                TaskList.guild_id == guild_id,
                TaskList.prefix == prefix,
            )
            .first()
        )
    if tasklist is None:
        return None, None
    return tasklist.id, tasklist.prefix


def create_tasklist(
    db: Session,
    guild_id: str,
    prefix: str,
    is_default: bool = False,  # noqa: FBT001, FBT002
) -> TaskList:
    """Create a new task list for the specified guild."""
    try:
        # 重複チェック
        existing = (
            db.query(TaskList)
            .filter(TaskList.guild_id == guild_id, TaskList.prefix == prefix)
            .first()
        )
        if existing is not None:
            msg = f"Task list with prefix '{prefix}' already exists"
            raise TasukuyaError(msg)

        # はじめてのリストかチェック
        is_first = db.query(TaskList).filter(TaskList.guild_id == guild_id).first()
        if is_first is not None:
            is_default = True

        task_list = TaskList(
            guild_id=guild_id,
            prefix=prefix,
            default=is_default,
        )
        db.add(task_list)
        db.commit()
        db.refresh(task_list)
    except TasukuyaError:
        # TasukuyaErrorはそのまま再発生
        raise
    except Exception as e:
        # 元の例外情報を保持してログに出力
        db.rollback()
        raise TasukuyaError(f"Failed to create task list: {e}") from e
    else:
        return task_list


def create_task(
    db: Session,
    task_list_id: str,
    task_name: str,
    due_date: str | None = None,
) -> Task:
    """
    Create a new task.

    1. retrieve the largest value from the task list.
    2. increment the value by 1 to get the next task ID.
    3. create a new task with the next task ID.
    """
    max_task_id = (
        db.query(Task)
        .filter(Task.task_list_id == task_list_id)
        .order_by(Task.task_id.desc())
        .first()
    )
    next_task_id = 1 if max_task_id is None else max_task_id.task_id + 1

    task = Task(
        task_list_id=task_list_id,
        task_id=next_task_id,
        task_name=task_name,
        due_date=parse_date(due_date),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_with_assignees(
    db: Session,
    task_list_id: str,
    task_id: int,
) -> tuple[Task, list[User]] | tuple[None, list[None]]:
    """指定したタスクとそのAssigneeユーザー一覧を返す"""
    task = (
        db.query(Task)
        .filter(Task.task_list_id == task_list_id, Task.task_id == task_id)
        .first()
    )
    if not task:
        return None, []
    assignees = (
        db.query(User)
        .join(TaskAssignee, User.user_id == TaskAssignee.user_id)
        .filter(
            TaskAssignee.task_list_id == task_list_id,
            TaskAssignee.task_id == task_id,
        )
        .all()
    )
    return task, assignees


# ...existing code...
def get_tasks(
    db: Session,
    task_list_id: int,
    assignee: str | None,
    max_entries: int = 30,
    page: int = 1,
    order_by_due_date: bool = True,
    is_done: bool = False,
) -> tuple[list[dict], int]:
    """
    Retrieve tasks with pagination and optional filtering by assignee and completion status.
    Returns: (tasks, total_pages)
    """
    # 入力検証
    if not isinstance(max_entries, int) or max_entries <= 0:
        msg = "max_entries must be a positive integer"
        raise ValueError(msg)
    if not isinstance(page, int) or page <= 0:
        msg = "page must be a positive integer"
        raise ValueError(msg)

    base_q = db.query(Task).filter(Task.task_list_id == task_list_id)
    if is_done:
        base_q = base_q.filter(Task.done_date.is_not(None))
    else:
        base_q = base_q.filter(Task.done_date.is_(None))

    if assignee is not None:
        base_q = base_q.join(
            TaskAssignee,
            and_(
                Task.task_list_id == TaskAssignee.task_list_id,
                Task.task_id == TaskAssignee.task_id,
            ),
        ).filter(TaskAssignee.user_id == assignee)

    # 総件数を先に取得 - offset/limit 前
    total_count = base_q.order_by(None).count()
    if order_by_due_date:
        base_q = base_q.order_by(Task.due_date.asc().nulls_last(), Task.task_id.asc())
    else:
        base_q = base_q.order_by(Task.task_id.asc())

    offset = (page - 1) * max_entries
    tasks = base_q.offset(offset).limit(max_entries).all()

    # プリミティブ化
    tasks_dicts = [
        {
            "task_list_id": t.task_list_id,
            "task_id": t.task_id,
            "task_name": t.task_name,
            "due_date": t.due_date,
            "done_date": t.done_date,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        }
        for t in tasks
    ]

    total_pages = (
        (total_count + max_entries - 1) // max_entries if total_count > 0 else 0
    )
    return tasks_dicts, total_pages


def assign_user(
    db: Session,
    task_list_id: str | None,
    task_id: int,  # str -> int に変更
    assignees: list[DiscordUser | DiscordMember],
    overwrite: bool = False,  # noqa: FBT001, FBT002
) -> tuple[Task, list[User]] | tuple[None, list[None]]:
    # assignees が単一オブジェクトで渡された場合に備える
    if not isinstance(assignees, (list, tuple)):
        assignees = [assignees]

    # overwrite のときは既存割当を削除 - delete は件数を返すので refresh しない
    if overwrite:
        db.query(TaskAssignee).filter(
            TaskAssignee.task_list_id == task_list_id,
            TaskAssignee.task_id == task_id,
        ).delete(synchronize_session=False)
        db.commit()

    # 対象タスクの存在確認 - 先に取得しておく
    task, _ = get_task_with_assignees(db, task_list_id, task_id)
    if task is None:
        return None, []

    # 新しいアサインを追加
    for u in assignees:
        # ユーザ作成 - 既存なら取得
        user = create_user_if_not_exists(
            db,
            str(u.id),
            getattr(
                u,
                "name",
                getattr(u, "display_name", str(u.id)),
            ),
        )
        # すでにアサインされていたら無視
        chk = (
            db.query(TaskAssignee)
            .filter(
                TaskAssignee.task_list_id == task_list_id,
                TaskAssignee.task_id == task_id,
                TaskAssignee.user_id == user.user_id,
            )
            .first()
        )
        if chk is not None:
            continue

        assign = TaskAssignee(
            task_list_id=task_list_id,
            task_id=task_id,
            user_id=user.user_id,
        )
        assign.user = user  # userオブジェクトを設定 - optional
        db.add(assign)
        db.commit()
        db.refresh(assign)

    # 最終的なタスクとアサイン済ユーザ一覧を返す
    task, assignees_users = get_task_with_assignees(db, task_list_id, task_id)
    return task, assignees_users


def unassign_user(
    db: Session,
    task_list_id: str | None,
    task_id: int,  # str -> int に変更
    assignees: list[DiscordUser | DiscordMember] | None,
) -> tuple[Task, list[User]] | tuple[None, list[None]]:
    # 対象タスクの存在確認 - 先に取得しておく
    task, _ = get_task_with_assignees(db, task_list_id, task_id)
    if task is None:
        return (None, [])

    if assignees is None:
        # assignees に None が指定されていたら、既存の assignees を削除
        _ = (
            db.query(TaskAssignee)
            .filter(
                TaskAssignee.task_list_id == task_list_id,
                TaskAssignee.task_id == task_id,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
    else:
        # 一致する assignees を削除
        assignees_id = [i.id for i in assignees]
        _ = (
            db.query(TaskAssignee)
            .filter(
                TaskAssignee.task_list_id == task_list_id,
                TaskAssignee.task_id == task_id,
                TaskAssignee.user_id.in_(assignees_id),
            )
            .delete()
        )
        db.commit()

    t, assignees = get_task_with_assignees(
        db,
        task_list_id,
        task_id,
    )

    return t, assignees


def mark_task_done(
    db: Session,
    task_list_id: str | None,
    task_id: int,  # str -> int に変更
) -> tuple[Task, list[User]] | tuple[None, list[None]]:
    task, assignees = get_task_with_assignees(db, task_list_id, task_id)
    if task is None:
        return None, []
    if task.done_date is not None:
        return task, assignees

    task.done_date = datetime.datetime.now(tz=ZoneInfo("Asia/Tokyo"))
    db.commit()
    db.refresh(task)

    return task, assignees


def mark_task_undone(
    db: Session,
    task_list_id: str | None,
    task_id: int,  # str -> int に変更
) -> tuple[Task, list[User]] | None:
    task, assignees = get_task_with_assignees(db, task_list_id, task_id)
    if task is None:
        return None, []
    if task.done_date is None:
        return task, assignees

    task.done_date = None
    db.commit()
    db.refresh(task)

    return task, assignees


def delete_task(
    db: Session,
    task_list_id: str | None,
    task_id: int,  # str -> int に変更
) -> tuple[Task] | None:
    task, _ = get_task_with_assignees(db, task_list_id, task_id)
    if task is None:
        return None
    copy = Task(
        task_list_id=task_list_id,
        task_id=task_id,
        task_name=task.task_name,
        due_date=task.due_date,
        done_date=task.done_date,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )

    # まず関連する TaskAssignee を削除
    db.query(TaskAssignee).filter(
        TaskAssignee.task_list_id == task_list_id,
        TaskAssignee.task_id == task_id,
    ).delete(synchronize_session=False)
    db.commit()

    # 次に Task 自体を削除
    db.delete(task)
    db.commit()

    return copy


def clone_task(
    db: Session,
    source_task_list_id: str | None,
    source_task_id: int,  # str -> int に変更
    target_task_list_id: str | None,
    task_name_suffix: str | None,
    assignees: list[DiscordUser | DiscordMember],
) -> tuple[Task, list[User]] | tuple[None, list[None]]:
    source_task, _ = get_task_with_assignees(
        db,
        source_task_list_id,
        source_task_id,
    )
    if source_task is None:
        return None, []
    new_task = create_task(
        db,
        target_task_list_id,
        source_task.task_name
        + (task_name_suffix if task_name_suffix is not None else ""),
        source_task.due_date.strftime("%Y%m%d%H%M")
        if source_task.due_date is not None
        else None,
    )
    if len(assignees) == 0:
        return new_task, []

    for assignee in assignees:
        _, result_assignees = assign_user(
            db,
            target_task_list_id,
            new_task.task_id,
            [assignee],
            False,
        )

    return new_task, result_assignees
