"""Concurrent MAVSDK pipe draining with native, not pipe-based, severity."""
import asyncio
import logging
import re


_LEVEL = re.compile(r"(?:\[|\|)\s*(debug|info|warn(?:ing)?|error)\s*\]", re.IGNORECASE)
_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING,
           "warning": logging.WARNING, "error": logging.ERROR}


def native_log_level(message: str) -> int:
    match = _LEVEL.search(message)
    if match:
        return _LEVELS[match.group(1).lower()]
    if any(marker in message.lower() for marker in ("error while loading shared libraries", "exec format error", "symbol lookup error")):
        return logging.ERROR
    return logging.DEBUG


async def drain_mavsdk_output(process, logger=None):
    logger = logger or logging.getLogger(__name__)

    async def drain(pipe, name):
        if pipe is None:
            return
        try:
            while line := await asyncio.to_thread(pipe.readline):
                message = line.decode(errors="replace").strip() if isinstance(line, bytes) else line.strip()
                if message:
                    logger.log(native_log_level(message), "MAVSDK [%s]: %s", name, message)
        except Exception:
            logger.exception("Error draining MAVSDK %s", name)

    # v4 normal logs are on stderr. Both pipes must be consumed while the server
    # is alive; reading stdout to EOF first can deadlock on a full stderr pipe.
    await asyncio.gather(drain(process.stdout, "stdout"), drain(process.stderr, "stderr"))
