import asyncio
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import storage, flatten, device, settings, firmware

APP_DIR = Path(__file__).parent


async def index(request: Request):
    return FileResponse(APP_DIR / "templates" / "index.html")


# ---------------------------------------------------------------------------
# Request body models (validated manually, no FastAPI)
# ---------------------------------------------------------------------------


class ScriptIn(BaseModel):
    name: str
    description: str = ""
    steps: list


class CopyIn(BaseModel):
    name: Optional[str] = None


class RunIn(BaseModel):
    times: Optional[int] = None


class SettingsIn(BaseModel):
    device_url: str


async def parse_body(request: Request, model):
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    try:
        return model.model_validate(raw), None
    except ValidationError as e:
        return None, JSONResponse({"detail": str(e)}, status_code=422)


def error(message: str, status_code: int = 400):
    return JSONResponse({"detail": message}, status_code=status_code)


# ---------------------------------------------------------------------------
# Scripts CRUD
# ---------------------------------------------------------------------------


async def api_list_scripts(request: Request):
    return JSONResponse(storage.list_scripts())


async def api_get_script(request: Request):
    script = storage.get_script(request.path_params["script_id"])
    if script is None:
        return error("script not found", 404)
    return JSONResponse(script)


async def api_create_script(request: Request):
    body, err = await parse_body(request, ScriptIn)
    if err:
        return err
    return JSONResponse(storage.save_script(None, body.name, body.description, body.steps))


async def api_update_script(request: Request):
    script_id = request.path_params["script_id"]
    if storage.get_script(script_id) is None:
        return error("script not found", 404)
    body, err = await parse_body(request, ScriptIn)
    if err:
        return err
    return JSONResponse(storage.save_script(script_id, body.name, body.description, body.steps))


async def api_delete_script(request: Request):
    if not storage.delete_script(request.path_params["script_id"]):
        return error("script not found", 404)
    return JSONResponse({"ok": True})


async def api_copy_script(request: Request):
    body, err = await parse_body(request, CopyIn)
    if err:
        return err
    copy = storage.copy_script(request.path_params["script_id"], body.name)
    if copy is None:
        return error("script not found", 404)
    return JSONResponse(copy)


async def api_preview_script(request: Request):
    script_id = request.path_params["script_id"]
    if storage.get_script(script_id) is None:
        return error("script not found", 404)
    return JSONResponse(flatten.preview(script_id))


# ---------------------------------------------------------------------------
# Device control
# ---------------------------------------------------------------------------


async def api_run_script(request: Request):
    script_id = request.path_params["script_id"]
    if storage.get_script(script_id) is None:
        return error("script not found", 404)
    body, err = await parse_body(request, RunIn)
    if err:
        return err
    try:
        flat = flatten.flatten_script(script_id)
    except flatten.FlattenError as e:
        return error(str(e))
    if not flat:
        return error("this script has no steps to run")
    try:
        await device.push_script(flat)
        await device.start(body.times)
    except device.DeviceError as e:
        return error(str(e), 502)
    settings.set_last_run(script_id, body.times)
    return JSONResponse({"ok": True, "step_count": len(flat)})


async def api_device_status(request: Request):
    try:
        return JSONResponse(await device.get_status())
    except device.DeviceError as e:
        return error(str(e), 502)


async def api_device_stop(request: Request):
    try:
        await device.stop()
    except device.DeviceError as e:
        return error(str(e), 502)
    # A manual stop means "I want this off", not "pause it for later" --
    # don't let a later deploy bring it back.
    settings.clear_last_run()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Firmware deploy
#
# This walks a whole sequence: let the current loop finish if something's
# running, send the new code, wait for the Pico to come back up from its
# restart, then put back whatever was running before. It can take anywhere
# from a few seconds to however long the script's current loop takes, so it
# runs in the background and the frontend polls api_deploy_status for
# progress instead of waiting on one long request.
# ---------------------------------------------------------------------------

deploy_state = {"phase": "idle", "message": ""}
DEPLOY_POLL_SECONDS = 1.5
DEPLOY_RESTART_TIMEOUT_SECONDS = 60


async def api_device_deploy(request: Request):
    if deploy_state["phase"] not in ("idle", "done", "error"):
        return error("a deploy is already in progress", 409)
    try:
        files = firmware.load_firmware_files()
    except firmware.FirmwareError as e:
        return error(str(e))
    asyncio.create_task(_run_deploy(files))
    return JSONResponse({"ok": True})


async def api_device_deploy_status(request: Request):
    return JSONResponse(deploy_state)


async def _run_deploy(files: dict):
    global deploy_state
    try:
        deploy_state = {"phase": "checking", "message": "Checking what's currently running..."}
        status = await device.get_status()
        last_run = settings.get_last_run() if status.get("running") else None

        if status.get("running"):
            deploy_state = {
                "phase": "waiting",
                "message": "Letting the current loop finish before deploying...",
            }
            await device.stop(after_current=True)
            while True:
                await asyncio.sleep(DEPLOY_POLL_SECONDS)
                try:
                    status = await device.get_status()
                except device.DeviceError:
                    continue
                if not status.get("running"):
                    break

        deploy_state = {"phase": "deploying", "message": "Sending new code to the Pico..."}
        await device.deploy_code(files)

        deploy_state = {"phase": "restarting", "message": "Waiting for the Pico to come back up..."}
        came_back = False
        waited = 0
        while waited < DEPLOY_RESTART_TIMEOUT_SECONDS:
            await asyncio.sleep(DEPLOY_POLL_SECONDS)
            waited += DEPLOY_POLL_SECONDS
            try:
                await device.get_status()
                came_back = True
                break
            except device.DeviceError:
                continue

        if not came_back:
            deploy_state = {
                "phase": "error",
                "message": (
                    "The Pico didn't come back up within a minute of restarting. "
                    "Check it directly -- it may need a manual power cycle."
                ),
            }
            return

        if last_run:
            deploy_state = {"phase": "resuming", "message": "Restarting your script..."}
            try:
                flat = flatten.flatten_script(last_run["script_id"])
                await device.push_script(flat)
                await device.start(last_run.get("times"))
            except (flatten.FlattenError, device.DeviceError) as e:
                deploy_state = {
                    "phase": "error",
                    "message": f"Deploy worked, but couldn't resume your script afterward: {e}",
                }
                return

        deploy_state = {"phase": "done", "message": "Deploy complete."}
    except device.DeviceError as e:
        deploy_state = {"phase": "error", "message": str(e)}
    except Exception as e:  # noqa: BLE001 -- surface anything unexpected rather than hang forever
        deploy_state = {"phase": "error", "message": f"Unexpected error during deploy: {e}"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


async def api_get_settings(request: Request):
    return JSONResponse({"device_url": settings.get_device_url()})


async def api_set_settings(request: Request):
    body, err = await parse_body(request, SettingsIn)
    if err:
        return err
    settings.set_device_url(body.device_url)
    return JSONResponse({"device_url": settings.get_device_url()})


routes = [
    Route("/", index),
    Route("/api/scripts", api_list_scripts, methods=["GET"]),
    Route("/api/scripts", api_create_script, methods=["POST"]),
    Route("/api/scripts/{script_id}", api_get_script, methods=["GET"]),
    Route("/api/scripts/{script_id}", api_update_script, methods=["PUT"]),
    Route("/api/scripts/{script_id}", api_delete_script, methods=["DELETE"]),
    Route("/api/scripts/{script_id}/copy", api_copy_script, methods=["POST"]),
    Route("/api/scripts/{script_id}/preview", api_preview_script, methods=["GET"]),
    Route("/api/scripts/{script_id}/run", api_run_script, methods=["POST"]),
    Route("/api/device/status", api_device_status, methods=["GET"]),
    Route("/api/device/stop", api_device_stop, methods=["POST"]),
    Route("/api/device/deploy", api_device_deploy, methods=["POST"]),
    Route("/api/device/deploy/status", api_device_deploy_status, methods=["GET"]),
    Route("/api/settings", api_get_settings, methods=["GET"]),
    Route("/api/settings", api_set_settings, methods=["PUT"]),
    Mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static"),
]

app = Starlette(routes=routes)
