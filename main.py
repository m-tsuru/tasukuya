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
    create_guild,
    create_task,
    create_tasklist,
    get_tasklist,
)

engine = create_engine("sqlite:///./tasukuya.db", echo=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

load_dotenv()

# 定数
COMMAND_PREFIX_DEFAULT = "/"
DISCORD_TOKEN_UNSETTED_DEFAULT = "UNSET"  # noqa: S105
DEBUG = True

# トークン
COMMAND_PREFIX = os.getenv("TASUKUYA_COMMAND_PREFIX", COMMAND_PREFIX_DEFAULT)
DISCORD_TOKEN = os.getenv("TASUKUYA_DISCORD_TOKEN", DISCORD_TOKEN_UNSETTED_DEFAULT)

intents = discord.Intents.default()

logger = logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)


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
        except Exception as e:
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
            message = f"サーバ {interaction.guild.id} で リスト プレフィックス {prefix} を作成しました"
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
            if get_tasklist is None:
                logger.error("No matching task list was found.")
                interaction.response.send_message("タスクリストが見つかりません")
        except ValueError as e:
            logger.exception("Failed to create the task:")
            interaction.response.send_message(f"タスクの作成に失敗しました: {e}")
        finally:
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
