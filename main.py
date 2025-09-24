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

    @bot.tree.command(name="ping", description="ping")
    async def ping(interaction: discord.Interaction) -> None:
        try:
            logger.info(
                "Echo Request - User: %s - %s",
                interaction.user.id,
                interaction.user.name,
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
