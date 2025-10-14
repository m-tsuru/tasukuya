import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lib.operate import (
    TasukuyaError,
    assign_user,
    create_guild,
    create_task,
    create_tasklist,
    get_task_with_assignees,
    get_tasklist,
    get_tasks,
    mark_task_done,
    mark_task_undone,
    parse_task_id,
    unassign_user,
)

engine = create_engine("sqlite:///./tasukuya.db", echo=True, future=True)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)

load_dotenv()

# 定数
COMMAND_PREFIX_DEFAULT = "/"
DISCORD_TOKEN_UNSETTED_DEFAULT = "UNSET"  # noqa: S105
DEBUG = True

# トークン
COMMAND_PREFIX = os.getenv("TASUKUYA_COMMAND_PREFIX", COMMAND_PREFIX_DEFAULT)
DISCORD_TOKEN = os.getenv("TASUKUYA_DISCORD_TOKEN", DISCORD_TOKEN_UNSETTED_DEFAULT)

intents = discord.Intents.default()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
# module-level logger
logger = logging.getLogger("tasukuya")
logger.setLevel(logging.INFO)


def format_dt(dt: datetime | None) -> str:
    """Format datetime for display in embeds."""
    if dt is None:
        return "未設定"
    return dt.strftime("%Y/%m/%d %H:%M")


async def _main() -> None:
    logger = logging.getLogger("tasukuya")
    logger.info("Startup Successfully...")

    bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

    stop_event = asyncio.Event()

    async def stop() -> None:
        await bot.close()
        logger.info("Shutdown Successfully")
        stop_event.set()

    @bot.event
    async def on_ready() -> None:
        await bot.tree.sync()
        logger.info("Logged in as %s", bot.user)

    @bot.event
    async def on_guild_join(guild: discord.Guild) -> None:
        logger.info("Joined guild: %s (id: %s)", guild.name, guild.id)
        logger.info("Add Guild to Database")
        try:
            with SessionLocal() as session:
                create_guild(
                    session,
                    guild_id=str(guild.id),
                    guild_name=guild.name,
                    create_user_id="0",
                )
        except Exception:
            logger.exception("An error occurred while adding guild to database")
        else:
            logger.info("Guild added to database successfully")

    @bot.tree.command(name="ping", description="ping")
    async def ping(interaction: discord.Interaction) -> None:
        try:
            logger.info(
                "Echo Request - User: %s - %s on %s",
                interaction.user.id,
                interaction.user.global_name,
                interaction.user.guild.id,
            )
            now = datetime.now(tz=ZoneInfo("Asia/Tokyo"))
            await interaction.response.send_message(
                f"Hello, {interaction.user.mention}. pong. ({now})",
            )
        except Exception as e:
            logger.exception("An error occurred during ping command")
            if DEBUG:
                await interaction.response.send_message(
                    f"Unexpected Error. [DEBUG]: {e}",
                )
            else:
                await interaction.response.send_message(
                    "Unexpected Error. Please contact service administrator.",
                )

    @bot.tree.command(name="setup", description="ToDo リストをセットアップします")
    async def setup(
        interaction: discord.Interaction,
        prefix: str,
    ) -> None:
        try:
            logger.info(
                "Setup Request - User: %s - %s on %s",
                interaction.user.id,
                interaction.user.global_name,
                interaction.user.guild.id,
            )
            with SessionLocal() as session:
                guild = create_guild(
                    session,
                    guild_id=str(interaction.guild.id),
                    guild_name=interaction.guild.name,
                    create_user_id=str(interaction.user.id),
                )
                _ = create_tasklist(
                    session,
                    guild_id=str(guild.guild_id),
                    prefix=prefix,
                )
            await interaction.response.send_message(
                f"Create New Task List: {prefix}",
            )
        except TasukuyaError as e:
            logger.exception("An Excepted Error has occured")
            await interaction.response.send_message(f"エラー: {e}")
        except Exception as e:
            logger.exception("An error occurred during setup command")
            if DEBUG:
                await interaction.response.send_message(
                    f"Unexpected Error. [DEBUG]: {e}",
                )
            else:
                await interaction.response.send_message(
                    "Unexpected Error. Please contact service administrator.",
                )
        else:
            message = f"サーバ {interaction.guild.id} で リスト {prefix} を作成しました"
            logger.info(message)
            await interaction.response.send_message(message)

    @bot.tree.command(name="create", description="タスクを作成します")
    async def create(
        interaction: discord.Interaction,
        task_name: str,
        due_date: discord.Optional[str] = None,
        task_list_prefix: discord.Optional[str] = None,
    ) -> None:
        try:
            msg = "Create Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task Name: {task_name}, "
            msg += f"Task List Prefix: {task_list_prefix}, "
            msg += f"Task Due Date: {due_date}"
            logger.info(msg)
            with SessionLocal() as session:
                task_id, task_prefix = get_tasklist(
                    session,
                    str(interaction.user.guild.id),
                    task_list_prefix,
                )
                task = create_task(
                    session,
                    task_id,
                    task_name,
                    due_date,
                )
            if task_id is None:
                logger.error("No matching task list was found.")
                await interaction.response.send_message("タスクリストが見つかりません")
                return
        except ValueError as e:
            logger.exception("Failed to create the task:")
            await interaction.response.send_message(f"タスクの作成に失敗しました: {e}")
        else:
            # 成功時のみ embed を作成して送信
            logger.info("Create Task List Successfully")
            embed = discord.Embed(
                title=f"[{task_prefix}-{task.task_id}] {task.task_name}",
                description="Created Task",
                color=0x00FF00,
            )
            formatted_time = (
                task.due_date.strftime("%Y/%m/%d %H:%M") if task.due_date else "未設定"
            )
            embed.add_field(name="Due Date", value=formatted_time)
            embed.add_field(name="Assignee", value="Not Assigned")
            embed.add_field(name="Done", value="Not yet")
            await interaction.response.send_message(
                f"**[{task_prefix}-{task.task_id}] {task.task_name}** が登録されました",
                embed=embed,
            )

    @bot.tree.command(name="assign", description="タスクにユーザをアサインします")
    async def assign(
        interaction: discord.Interaction,
        task_id: str,
        assignee: discord.User,
    ) -> None:
        try:
            msg = "Assign Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}"
            logger.info(msg)
            t_prefix_like, t_id_like = parse_task_id(task_id)
            with SessionLocal() as session:
                task_list_id, task_list_prefix = get_tasklist(
                    session,
                    interaction.guild_id,
                    t_prefix_like,
                )
                if task_list_id is None:
                    if t_prefix_like is None:
                        msg = "このサーバでデフォルトに指定されているタスクリストがありません"  # noqa: E501
                    else:
                        msg = "一致するタスクリストがありません"
                    raise ValueError(msg)  # noqa: TRY301
                task, _ = get_task_with_assignees(session, task_list_id, t_id_like)
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301

                # セッション内でタスク情報を取得
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                }

                _, a = assign_user(
                    session,
                    task_list_id,
                    t_id_like,
                    [assignee],  # assigneeをリストに変更
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301

                # セッション内でユーザー名を取得
                task_assignees = " ".join(
                    [f"<@{i.user_id}>" for i in a],
                )
            logger.info("Create Assign Successfully")
            embed = discord.Embed(
                title=f"[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",  # noqa: E501
                description="Assign Completed",
                color=0x00FF00,
            )
            formatted_time = (
                task_info["due_date"].strftime("%Y/%m/%d %H:%M")
                if task_info["due_date"]
                else "未設定"
            )
            embed.add_field(name="Assignees", value=task_assignees)
            embed.add_field(name="Due Date", value=formatted_time)
            embed.add_field(name="Done", value="Not yet")
            await interaction.response.send_message(
                f"**[{task_list_prefix}-{task_info['task_id']}] "
                f"{task_info['task_name']}** に "
                f"**{task_assignees}** がアサインされました",
                embed=embed,
            )
        except Exception as e:
            logger.exception("タスクのアサイン中にエラーが発生しました:")
            await interaction.response.send_message(
                f"タスクのアサイン中にエラーが発生しました: {e}",
            )

    @bot.tree.command(name="unassign", description="タスクからユーザを解放します")
    async def unassign(
        interaction: discord.Interaction,
        task_id: str,
        user: discord.User | None = None,
    ) -> None:
        try:
            task_assignees = []
            with SessionLocal() as session:
                msg = "Unassign Task Request:, "
                msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
                msg += f"Task ID: {task_id}"
                logger.info(msg)
                t_prefix_like, t_id_like = parse_task_id(task_id)
                task_list_id, task_list_prefix = get_tasklist(
                    session,
                    interaction.guild_id,
                    t_prefix_like,
                )
                if task_list_id is None:
                    if t_prefix_like is None:
                        msg = "このサーバでデフォルトに指定されているタスクリストがありません"
                    else:
                        msg = "一致するタスクリストがありません"
                    raise ValueError(msg)
                if user is None:
                    task, assignees = unassign_user(
                        session,
                        task_list_id,
                        t_id_like,
                        None,
                    )
                else:
                    task, assignees = unassign_user(
                        session,
                        task_list_id,
                        t_id_like,
                        [user],
                    )
                if task is None:
                    raise ValueError("一致するタスクがありません")
                # セッション内で必要な task 情報を取り出しておく
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                }
                task_assignees = " ".join([f"<@{i.user_id}>" for i in assignees])
        except Exception as e:
            logger.exception("Failed to unassign user from the task:")
            await interaction.response.send_message(
                f"タスクのアサイン解除に失敗しました: {e}",
            )
            return

        # 成功時のレスポンス - session は閉じられているが task_info を使う
        logger.info("Success to unassign user from the task")
        embed = discord.Embed(
            title=f"[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",
            description="Unassign Completed",
            color=0x00FF00,
        )
        formatted_time = (
            task_info["due_date"].strftime("%Y/%m/%d %H:%M")
            if task_info["due_date"]
            else "未設定"
        )
        embed.add_field(name="Due Date", value=formatted_time)
        embed.add_field(name="Assignee", value=task_assignees or "Not Assigned")
        embed.add_field(name="Done", value="Not yet")
        await interaction.response.send_message(
            f"**[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}** から **{task_assignees or 'Not Assigned'}** にアサインされました",
            embed=embed,
        )

    @bot.tree.command(name="done", description="タスクを完了済みにします")
    async def done(
        interaction: discord.Interaction,
        task_id: str,
    ) -> None:
        try:
            msg = "Mark Task Done Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}"
            logger.info(msg)
            t_prefix_like, t_id_like = parse_task_id(task_id)
            with SessionLocal() as session:
                task_list_id, task_list_prefix = get_tasklist(
                    session,
                    interaction.guild_id,
                    t_prefix_like,
                )
                if task_list_id is None:
                    if t_prefix_like is None:
                        msg = "このサーバでデフォルトに指定されているタスクリストがありません"  # noqa: E501
                    else:
                        msg = "一致するタスクリストがありません"
                    raise ValueError(msg)  # noqa: TRY301
                task, assignees = mark_task_done(
                    session,
                    task_list_id,
                    t_id_like,
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301

                # セッション内でタスク情報を取得
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                    "done_date": task.done_date,
                }

                # セッション内でユーザー名を取得
                task_assignees = " ".join(
                    [f"<@{i.user_id}>" for i in assignees],
                )
            logger.info("Mark Task Done Successfully")
            embed = discord.Embed(
                title=f"[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",  # noqa: E501
                description="Marked as Done",
                color=0x00FF00,
            )
            formatted_due = (
                task_info["due_date"].strftime("%Y/%m/%d %H:%M")
                if task_info["due_date"]
                else "未設定"
            )
            formatted_done = (
                task_info["done_date"].strftime("%Y/%m/%d %H:%M")
                if task_info["done_date"]
                else "Not yet"
            )
            embed.add_field(name="Assignees", value=task_assignees or "Not Assigned")
            embed.add_field(name="Due Date", value=formatted_due)
            embed.add_field(name="Done", value=formatted_done)
            await interaction.response.send_message(
                f"**[{task_list_prefix}-{task_info['task_id']}] "
                f"{task_info['task_name']}** を完了済みにしました",
                embed=embed,
            )
        except Exception as e:
            logger.exception("Failed to mark task as done:")
            await interaction.response.send_message(
                f"タスクの完了済みへの変更に失敗しました: {e}",
            )

    @bot.tree.command(name="undone", description="タスクを未完了にします")
    async def undone(
        interaction: discord.Interaction,
        task_id: str,
    ) -> None:
        try:
            msg = "Mark Task Undone Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}"
            logger.info(msg)
            t_prefix_like, t_id_like = parse_task_id(task_id)
            with SessionLocal() as session:
                task_list_id, task_list_prefix = get_tasklist(
                    session,
                    interaction.guild_id,
                    t_prefix_like,
                )
                if task_list_id is None:
                    if t_prefix_like is None:
                        msg = "このサーバでデフォルトに指定されているタスクリストがありません"  # noqa: E501
                    else:
                        msg = "一致するタスクリストがありません"
                    raise ValueError(msg)  # noqa: TRY301
                task, assignees = mark_task_undone(
                    session,
                    task_list_id,
                    t_id_like,
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301

                # セッション内でタスク情報を取得
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                    "done_date": task.done_date,
                }

                # セッション内でユーザー名を取得
                task_assignees = " ".join(
                    [f"<@{i.user_id}>" for i in assignees],
                )
            logger.info("Mark Task Undone Successfully")
            embed = discord.Embed(
                title=f"[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",  # noqa: E501
                description="Marked as Undone",
                color=0x00FF00,
            )
            formatted_due = (
                task_info["due_date"].strftime("%Y/%m/%d %H:%M")
                if task_info["due_date"]
                else "未設定"
            )
            formatted_done = (
                task_info["done_date"].strftime("%Y/%m/%d %H:%M")
                if task_info["done_date"]
                else "Not yet"
            )
            embed.add_field(name="Assignees", value=task_assignees or "Not Assigned")
            embed.add_field(name="Due Date", value=formatted_due)
            embed.add_field(name="Done", value=formatted_done)
            await interaction.response.send_message(
                f"**[{task_list_prefix}-{task_info['task_id']}] "
                f"{task_info['task_name']}** を未完了にしました",
                embed=embed,
            )
        except Exception as e:
            logger.exception("Failed to mark task as undone:")
            await interaction.response.send_message(
                f"タスクの未完了への変更に失敗しました: {e}",
            )

    @bot.tree.command(name="list", description="タスク一覧を出力します")
    async def list_tasks(
        interaction: discord.Interaction,
        task_list_prefix: discord.Optional[str] = None,
        assignee: discord.User | None = None,
        page: int = 1,
        max_entries: int = 30,
        order_by_due: bool = False,
        is_done: bool = False,
    ) -> None:
        try:
            msg = "List Tasks Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task List Prefix: {task_list_prefix}, "
            msg += f"Assignee: {assignee}, "
            msg += f"Page: {page}, "
            msg += f"Order By Due: {order_by_due}, "
            msg += f"Is Done: {is_done}"
            logger.info(msg)
            with SessionLocal() as session:
                task_list_id, task_list_prefix = get_tasklist(
                    session,
                    interaction.guild_id,
                    task_list_prefix,
                )
                if task_list_id is None:
                    if task_list_prefix is None:
                        msg = "このサーバでデフォルトに指定されているタスクリストがありません"  # noqa: E501
                    else:
                        msg = "一致するタスクリストがありません"
                    raise ValueError(msg)  # noqa: TRY301
                tasks, total_pages = get_tasks(
                    session,
                    task_list_id,
                    str(assignee.id) if assignee else None,
                    max_entries,
                    page,
                    order_by_due,
                    is_done,
                )
                if not tasks:
                    await interaction.response.send_message(
                        "該当するタスクがありません",
                    )
                    return
                embed = discord.Embed(
                    title=f"Task List: {task_list_prefix}",
                    description=f"Page {page} of {total_pages}",
                    color=0x00FF00,
                )
                for task in tasks:
                    # task は dict なのでキーでアクセス
                    # セッション内で assignees を取得（User オブジェクトのリストが返る）
                    _, assignees_list = get_task_with_assignees(
                        session, task_list_id, task["task_id"]
                    )
                    assignees = (
                        ", ".join([f"<@{a.user_id}>" for a in assignees_list])
                        or "Not Assigned"
                    )
                    due_date = (
                        task["due_date"].strftime("%Y/%m/%d %H:%M")
                        if task["due_date"]
                        else "未設定"
                    )
                    done_date = (
                        task["done_date"].strftime("%Y/%m/%d %H:%M")
                        if task["done_date"]
                        else "Not yet"
                    )
                    embed.add_field(
                        name=f"[{task_list_prefix}-{task['task_id']}] {task['task_name']}",
                        value=(
                            f"Assignees: {assignees}\n"
                            f"Due Date: {due_date}\n"
                            f"Done: {done_date}"
                        ),
                        inline=False,
                    )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            logger.exception("Failed to list tasks:")
            await interaction.response.send_message(
                f"タスクの一覧取得に失敗しました: {e}",
            )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(stop()))

    if DISCORD_TOKEN == DISCORD_TOKEN_UNSETTED_DEFAULT:
        logger.error("Discord Token is unset")
        sys.exit(1)

    await bot.start(token=DISCORD_TOKEN)
    await stop_event.wait()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
