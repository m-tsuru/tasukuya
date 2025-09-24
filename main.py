import asyncio
import signal


async def _main() -> None:
    stop_event = asyncio.Event()

    async def stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(stop()))
    await stop_event.wait()


async def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
