import asyncio
import signal
import sys

import discord
from discord.ext import commands

# 定数
COMMAND_PREFIX_DEFAULT = "/"
DISCORD_TOKEN_UNSETTED_DEFAULT = "UNSET"  # noqa: S105

# トークン
DISCORD_TOKEN = "UNSET"  # noqa: S105

intents = discord.Intents.default()
intents.message_content = True


async def _main() -> None:
    bot = commands.Bot(command_prefix=COMMAND_PREFIX_DEFAULT, intents=intents)

    stop_event = asyncio.Event()

    async def stop() -> None:
        await bot.close()
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(stop()))

    if DISCORD_TOKEN == DISCORD_TOKEN_UNSETTED_DEFAULT:
        sys.exit(1)

    await bot.start()
    await stop_event.wait()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
