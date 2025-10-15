import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lib.operate import (
    TasukuyaError,
    assign_user,
    clone_task,
    create_guild,
    create_task,
    create_tasklist,
    delete_task,
    get_task_with_assignees,
    get_tasklist,
    get_tasks,
    mark_task_done,
    mark_task_undone,
    parse_task_id,
    rename_task,
    reschedule_task,
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

    @bot.tree.command(name="ping", description="ガンを飛ばす")
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
    @app_commands.describe(
        prefix="タスクを指定するときのプレフィックス。タスクを指定するときに付与します",
    )
    async def setup(
        interaction: discord.Interaction,
        prefix: str,
    ) -> None:
        try:
            logger.info(
                "Setup Request - User: %s - %s on %s, prefix: %s",
                interaction.user.id,
                interaction.user.global_name,
                interaction.user.guild.id,
                prefix,
            )
            with SessionLocal() as session:
                guild = create_guild(
                    session,
                    guild_id=str(interaction.guild.id),
                    guild_name=interaction.guild.name,
                    create_user_id=str(interaction.user.id),
                )
                logger.info("Guild created/retrieved: %s", guild.guild_id)
                task_list = create_tasklist(
                    session,
                    guild_id=str(guild.guild_id),
                    prefix=prefix,
                )
                logger.info("Task list created: %s", task_list.id)
        except TasukuyaError as e:
            logger.exception("Tasukuya Error occurred during setup")
            await interaction.response.send_message(f"エラー: {e}")
            return
        except Exception as e:
            logger.exception("Unexpected error occurred during setup")
            if DEBUG:
                await interaction.response.send_message(
                    f"Unexpected Error. [DEBUG]: {e}",
                )
            else:
                await interaction.response.send_message(
                    "Unexpected Error. Please contact service administrator.",
                )
            return

        # 成功時の処理
        message = f"サーバ {interaction.guild.name} で リスト {prefix} を作成しました"
        logger.info(message)
        await interaction.response.send_message(message)

    @bot.tree.command(name="create", description="タスクを作成します")
    @app_commands.describe(
        name="タスクの名前",
        due_date="タスクの期限 (形式: MMDD, MMDDf, YYYYMMDD, YYYYMMDDHHmm))",
        task_list_prefix="タスクリストのプレフィックス(省略時はデフォルトのタスクリスト)",
    )
    async def create(
        interaction: discord.Interaction,
        name: str,
        due_date: discord.Optional[str] = None,
        task_list_prefix: discord.Optional[str] = None,
    ) -> None:
        try:
            msg = "Create Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task Name: {name}, "
            msg += f"Task List Prefix: {task_list_prefix}, "
            msg += f"Task Due Date: {due_date}"
            logger.info(msg)
            with SessionLocal() as session:
                task_list_id, task_prefix = get_tasklist(
                    session,
                    str(interaction.user.guild.id),
                    task_list_prefix,
                )
                if task_list_id is None:
                    logger.error("No matching task list was found.")
                    await interaction.response.send_message(
                        "タスクリストが見つかりません",
                    )
                    return
                task = create_task(
                    session,
                    task_list_id,
                    name,
                    due_date,
                )
                task, assignees = assign_user(
                    session,
                    task_list_id,
                    task.task_id,
                    [interaction.user],
                    False,
                )
                assignees_text = " ".join([f"<@{i.user_id}>" for i in assignees])
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
            embed.add_field(
                name="Assignee",
                value=assignees_text if assignees_text else "Not Assigned",
            )
            embed.add_field(name="Done", value="Not yet")
            await interaction.response.send_message(
                f"**[{task_prefix}-{task.task_id}] {task.task_name}** が登録されました",
                embed=embed,
            )
        except ValueError as e:
            logger.exception("Failed to create the task:")
            await interaction.response.send_message(f"タスクの作成に失敗しました: {e}")

    @bot.tree.command(name="assign", description="タスクにユーザをアサインします")
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
        assignee="アサインしたいユーザ",
    )
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
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
        user="アサインを解除したいユーザ (省略時はコマンド実行者)",
    )
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
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)
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
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
    )
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
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
    )
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
        assignee: discord.User | None = None,
        task_list_prefix: discord.Optional[str] = None,
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
                    str(assignee.id) if assignee else str(interaction.user.id),
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
                    # セッション内で assignees を取得 - User オブジェクトのリストが返る
                    _, assignees_list = get_task_with_assignees(
                        session,
                        task_list_id,
                        task["task_id"],
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

    @bot.tree.command(name="delete", description="タスクを削除します")
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
    )
    async def delete(
        interaction: discord.Interaction,
        task_id: int,
    ) -> None:
        try:
            msg = "Delete Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}"
            logger.info(msg)
            t_prefix_like, t_id_like = parse_task_id(str(task_id))
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
                task = delete_task(
                    session,
                    task_list_id,
                    t_id_like,
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                    "done_date": task.done_date,
                }
            logger.info("Delete Task Successfully")
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
            embed.add_field(name="Due Date", value=formatted_due)
            embed.add_field(name="Done", value=formatted_done)
            await interaction.response.send_message(
                f"**[{task_list_prefix}-{t_id_like}]** を削除しました",
                embed=embed,
            )
        except Exception as e:
            logger.exception("Failed to delete the task:")
            await interaction.response.send_message(
                f"タスクの削除に失敗しました: {e}",
            )

    @bot.tree.command(name="rename", description="タスク名を変更します")
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
        new_name="新しいタスク名",
    )
    async def rename(
        interaction: discord.Interaction,
        task_id: str,
        new_name: str,
    ) -> None:
        try:
            msg = "Rename Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}, "
            msg += f"New Name: {new_name}"
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
                task, _ = rename_task(
                    session,
                    task_list_id,
                    t_id_like,
                    new_name,
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                    "done_date": task.done_date,
                }
            logger.info("Rename Task Successfully")
            embed = discord.Embed(
                title=f"[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",  # noqa: E501
                description="Renamed Task",
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
            embed.add_field(name="Due Date", value=formatted_due)
            embed.add_field(name="Done", value=formatted_done)
            await interaction.response.send_message(
                f"**[{task_list_prefix}-{task_info['task_id']}]** の名前を変更しました",
                embed=embed,
            )
            logger.info("Rename Task Successfully")
        except Exception as e:
            logger.exception("Failed to rename the task:")
            await interaction.response.send_message(
                f"タスクの名前変更に失敗しました: {e}",
            )

    @bot.tree.command(name="reschedule", description="タスクの期限を変更します")
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
        new_due_date="新しい期限 (形式: MMDD, MMDDf, YYYYMMDD, YYYYMMDDHHmm))",
    )
    async def reschedule(
        interaction: discord.Interaction,
        task_id: str,
        new_due_date: str,
    ) -> None:
        try:
            msg = "Reschedule Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}, "
            msg += f"New Due Date: {new_due_date}"
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
                task, _ = reschedule_task(
                    session,
                    task_list_id,
                    t_id_like,
                    new_due_date,
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                    "done_date": task.done_date,
                }
            logger.info("Reschedule Task Successfully")
            embed = discord.Embed(
                title=f"[{task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",  # noqa: E501
                description="Rescheduled Task",
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
            embed.add_field(name="Due Date", value=formatted_due)
            embed.add_field(name="Done", value=formatted_done)
            await interaction.response.send_message(
                f"**[{task_list_prefix}-{task_info['task_id']}]** の期限を変更しました",
                embed=embed,
            )
            logger.info("Reschedule Task Successfully")
        except Exception as e:
            logger.exception("Failed to reschedule the task:")
            await interaction.response.send_message(
                f"タスクの期限変更に失敗しました: {e}",
            )

    @bot.tree.command(name="clone", description="タスクをクローンします")
    @app_commands.describe(
        task_id="タスクのID (例: PREFIX-1, 1)",
        target_task_list_id="クローン先のタスクリストID (省略時は元のタスクリスト)",
        task_name_suffix="クローン後のタスク名に付与するサフィックス (省略時は '(cloned by ユーザ名)')",  # noqa: E501
    )
    async def clone(
        interaction: discord.Interaction,
        task_id: str,
        target_task_list_id: str | None,
        task_name_suffix: discord.Optional[str] = None,
    ) -> None:
        try:
            msg = "Clone Task Request:, "
            msg += f"User: {interaction.user.global_name} ({interaction.user.id}), "
            msg += f"Task ID: {task_id}, "
            msg += f"Target Task List ID: {target_task_list_id}"
            logger.info(msg)
            t_prefix_like, t_id_like = parse_task_id(task_id)
            with SessionLocal() as session:
                source_task_list_id, source_task_list_prefix = get_tasklist(
                    session,
                    interaction.guild_id,
                    t_prefix_like,
                )
                if source_task_list_id is None:
                    if t_prefix_like is None:
                        msg = "このサーバでデフォルトに指定されているタスクリストがありません"  # noqa: E501
                    else:
                        msg = "一致するタスクリストがありません"
                    raise ValueError(msg)  # noqa: TRY301
                if target_task_list_id is None:
                    target_task_list_id = source_task_list_id
                task, assignees = clone_task(
                    session,
                    source_task_list_id,
                    t_id_like,
                    target_task_list_id,
                    f" (cloned by {interaction.user.global_name})"
                    if task_name_suffix is None
                    else " (" + task_name_suffix + ")",
                    [interaction.user],
                )
                if task is None:
                    msg = "一致するタスクがありません"
                    raise ValueError(msg)  # noqa: TRY301

                # セッション内でタスク情報を取得
                task_info = {
                    "task_id": task.task_id,
                    "task_name": task.task_name,
                    "due_date": task.due_date,
                }

                # セッション内でユーザー名を取得
                task_assignees = " ".join(
                    [f"<@{i.user_id}>" for i in assignees],
                )
            logger.info("Clone Task Successfully")
            embed = discord.Embed(
                title=f"[{source_task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}",  # noqa: E501
                description="Cloned Task",
                color=0x00FF00,
            )
            formatted_time = (
                task_info["due_date"].strftime("%Y/%m/%d %H:%M")
                if task_info["due_date"]
                else "未設定"
            )
            embed.add_field(name="Due Date", value=formatted_time)
            embed.add_field(
                name="Assignee",
                value=task_assignees if task_assignees else "Not Assigned",
            )
            embed.add_field(name="Done", value="Not yet")
            await interaction.response.send_message(
                f"**[{source_task_list_prefix}-{task_info['task_id']}] {task_info['task_name']}** がクローンされました",  # noqa: E501
                embed=embed,
            )
        except Exception as e:
            logger.exception("Failed to clone the task:")
            await interaction.response.send_message(
                f"タスクのクローンに失敗しました: {e}",
            )
            msg = "Failed to clone the task:"
            logger.exception(msg)

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
