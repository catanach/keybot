"""Talks to whichever device is configured (the local dev server or the
real Pico) over the same HTTP API used everywhere else in this project:
/status, /start, /stop, /update.
"""

import asyncio

import httpx

from . import settings

TIMEOUT = 5.0

# Writing two source files to the board's flash takes longer than reading
# its status, and sharing one timeout meant a slow deploy looked like an
# unreachable board.
DEPLOY_TIMEOUT = 30.0

# The Pico serves HTTP from a single-threaded poll loop: it accepts one
# connection at a time. Once the webapp gained a background history poller
# there were two callers, and a status poll landing while a deploy was
# talking to the board got the connection dropped on the floor, which the
# webapp then reported as "Server disconnected without sending a response".
# Every call from the webapp goes through this lock so the board only ever
# has one conversation at a time.
_device_lock = asyncio.Lock()


class DeviceError(Exception):
    """Raised when the configured device can't be reached or returns an
    error. The message is meant to be shown directly to the user."""


async def get_status() -> dict:
    url = f"{settings.get_device_url()}/status"
    try:
        async with _device_lock, httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device returned an error: {resp.text}")
    return resp.json()


async def push_script(steps: list) -> None:
    url = f"{settings.get_device_url()}/update"
    try:
        async with _device_lock, httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=steps)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device rejected the script: {resp.text}")


async def start(times: int | None = None) -> None:
    url = f"{settings.get_device_url()}/start"
    # `if times` would drop times=0, and a missing times means "run forever"
    # on the device, which is the opposite of what was asked for.
    params = {"times": times} if times is not None else {}
    try:
        async with _device_lock, httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device refused to start: {resp.text}")


async def stop(after_current: bool = False) -> None:
    """Stops the running script. With after_current=True, it lets the pass
    in progress finish first instead of cutting it off mid-step -- used
    before a firmware deploy so a step doesn't get interrupted partway."""
    url = f"{settings.get_device_url()}/stop"
    params = {"after_current": "1"} if after_current else {}
    try:
        async with _device_lock, httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device refused to stop: {resp.text}")


async def set_host_writes(enabled: bool) -> None:
    """Asks the board to hand its drive back to the Mac, or to take it back.

    Takes effect on the board's next power cycle. This is the recovery path
    that does not need safe mode, which matters because a Pico W has no
    reset button."""
    url = f"{settings.get_device_url()}/host_writes"
    params = {"enabled": "1" if enabled else "0"}
    try:
        async with _device_lock, httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device refused: {resp.text}")


async def deploy_code(files: dict) -> None:
    """Sends new firmware source to the device. The device writes the
    files and restarts itself to pick them up -- only call this once
    you've confirmed nothing is running."""
    url = f"{settings.get_device_url()}/deploy_code"
    # One file per request. Sending both at once meant the board had to hold
    # and parse a single ~19KB JSON body, and it ran out of memory doing it:
    # "MemoryError: memory allocation failed, allocating 19075 bytes". The
    # board restarts after each file, so the caller must send them in an
    # order where a half-updated board still boots -- see DEPLOY_FILES.
    for name, content in files.items():
        try:
            async with _device_lock, httpx.AsyncClient(timeout=DEPLOY_TIMEOUT) as client:
                resp = await client.post(url, json={name: content})
        except httpx.RequestError as e:
            # The board resets as soon as it has written the file, so the
            # reply is often cut off. That is success, not failure.
            if _looks_like_a_restart(e):
                await _wait_for_device_back()
                continue
            raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
        if resp.status_code != 200:
            raise DeviceError(f"device rejected the deploy: {resp.text}")
        await _wait_for_device_back()


def _looks_like_a_restart(e) -> bool:
    text = str(e).lower()
    return "disconnected" in text or "incomplete" in text or "peer closed" in text


async def _wait_for_device_back(timeout: float = 45.0) -> None:
    """Waits for the board to answer again after it restarts itself."""
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(3.0)
        waited += 3.0
        try:
            await get_status()
            return
        except DeviceError:
            continue
    raise DeviceError(
        "the Pico did not come back after a firmware file was written. "
        "Unplug it and plug it back in, then check the Firmware panel."
    )
