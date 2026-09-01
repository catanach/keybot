"""Talks to whichever device is configured (the local dev server or the
real Pico) over the same HTTP API used everywhere else in this project:
/status, /start, /stop, /update.
"""

import httpx

from . import settings

TIMEOUT = 5.0


class DeviceError(Exception):
    """Raised when the configured device can't be reached or returns an
    error. The message is meant to be shown directly to the user."""


async def get_status() -> dict:
    url = f"{settings.get_device_url()}/status"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device returned an error: {resp.text}")
    return resp.json()


async def push_script(steps: list) -> None:
    url = f"{settings.get_device_url()}/update"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=steps)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device rejected the script: {resp.text}")


async def start(times: int | None = None) -> None:
    url = f"{settings.get_device_url()}/start"
    params = {"times": times} if times else {}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device refused to start: {resp.text}")


async def stop() -> None:
    url = f"{settings.get_device_url()}/stop"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.RequestError as e:
        raise DeviceError(f"can't reach device at {settings.get_device_url()}: {e}")
    if resp.status_code != 200:
        raise DeviceError(f"device refused to stop: {resp.text}")
