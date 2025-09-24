import asyncio
import logging
import signal
import sys
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# 定数
COMMAND_PREFIX_DEFAULT = "/"
DISCORD_TOKEN_UNSETTED_DEFAULT = "UNSET"  # noqa: S105

# トークン
COMMAND_PREFIX = os.getenv("TASUKUYA_COMMAND_PREFIX", COMMAND_PREFIX_DEFAULT)
DISCORD_TOKEN = os.getenv("TASUKUYA_DISCORD_TOKEN", DISCORD_TOKEN_UNSETTED_DEFAULT)

intents = discord.Intents.default()
intents.message_content = True

logger = logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)


async def _main() -> None:
    logger = logging.getLogger("tasukuya")

    bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

    stop_event = asyncio.Event()

    async def stop() -> None:
        await bot.close()
        logger.info("Shutdown Successfully")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(stop()))

    if DISCORD_TOKEN == DISCORD_TOKEN_UNSETTED_DEFAULT:
        logger.error("Discord Token is unset")
        sys.exit(1)

    await bot.start()
    logger.info("Startup Successfully")
    await stop_event.wait()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
