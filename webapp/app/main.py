import asyncio
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import storage, flatten, device, settings, firmware, history

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
    # Remember this stop came from us, so the run is recorded as one you
    # stopped rather than one that merely ended.
    note_stop_sent()
    try:
        await device.stop()
    except device.DeviceError as e:
        return error(str(e), 502)
    # A manual stop means "I want this off", not "pause it for later" --
    # don't let a later deploy bring it back.
    settings.clear_last_run()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Run history
#
# One background task polls the device every 5 seconds regardless of what
# any browser is doing, and writes one history record per run. A record is
# opened when the device goes from not running to running, and closed when
# it goes back. Deriving records from the device this way, rather than from
# the Start button, means a run started by a firmware deploy is recorded
# just like one started by hand -- and a run that ends at 3am with nobody
# watching still gets its ending written down.
# ---------------------------------------------------------------------------

log = logging.getLogger("keybot")

HISTORY_POLL_SECONDS = 5

# How many polls in a row have to fail before we give up on a run. A Pico W
# on Wi-Fi drops the odd request, and treating the first miss as the end of
# the run split one healthy job into two rows with a "lost contact" that
# never happened. Three misses is 15 seconds of silence, which is a real
# outage rather than a blip.
LOST_CONTACT_AFTER_FAILED_POLLS = 3

# The run currently being recorded, if any. we_stopped_it remembers that
# the stop came from us, which is the whole difference between "you
# stopped it" and "it stopped".
open_run = {"record_id": None, "loops_done": 0, "we_stopped_it": False,
            "failed_polls": 0}

_poller_task = None


def note_stop_sent() -> None:
    open_run["we_stopped_it"] = True


def _forget_open_run() -> None:
    open_run["record_id"] = None
    open_run["loops_done"] = 0
    open_run["we_stopped_it"] = False
    open_run["failed_polls"] = 0


def _script_name(script_id) -> str:
    script = storage.get_script(script_id) if script_id else None
    return script["name"] if script else "(unknown script)"


async def _poll_device_once() -> None:
    # A deploy deliberately stops the script and restarts the board. Polling
    # through that would record a run that ended normally as a lost one, and
    # would put a second caller on a board that answers one at a time.
    if deploy_state.get("phase") not in ("idle", "done", "error"):
        return

    try:
        status = await device.get_status()
    except device.DeviceError as e:
        # The device stopped answering. An unrecorded disappearance is the
        # thing this feature exists to fix, but a single dropped request is
        # not a disappearance -- only give up after several in a row.
        if open_run["record_id"] is not None:
            open_run["failed_polls"] += 1
            if open_run["failed_polls"] >= LOST_CONTACT_AFTER_FAILED_POLLS:
                history.close_record(
                    open_run["record_id"], open_run["loops_done"], history.LOST_CONTACT, str(e)
                )
                _forget_open_run()
        return

    open_run["failed_polls"] = 0

    if status.get("running"):
        if open_run["record_id"] is None:
            script_id = (settings.get_last_run() or {}).get("script_id")
            open_run["record_id"] = history.open_record(
                script_id, _script_name(script_id), status.get("target_loops")
            )
            open_run["we_stopped_it"] = False
        open_run["loops_done"] = status.get("loop_count", 0)
    elif open_run["record_id"] is not None:
        # last_error has to be read here, on the poll that sees the run
        # end: the next /start wipes it off the device.
        last_error = status.get("last_error")
        loops_done = status.get("loop_count", open_run["loops_done"])
        outcome = history.outcome_for(
            loops_done, status.get("target_loops"), last_error, open_run["we_stopped_it"]
        )
        history.close_record(open_run["record_id"], loops_done, outcome, last_error)
        _forget_open_run()


async def _poll_device_forever() -> None:
    while True:
        try:
            await _poll_device_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- one bad poll must not end all recording
            log.exception("run-history poll failed")
        await asyncio.sleep(HISTORY_POLL_SECONDS)


async def start_history_poller() -> None:
    global _poller_task
    # A record still open means this app stopped while a run was going --
    # a container restart, a crash -- and nobody is left to close it.
    orphans = history.close_open_records()
    if orphans:
        log.warning("closed %d run(s) left open when this app last stopped", orphans)
    _poller_task = asyncio.create_task(_poll_device_forever())


async def stop_history_poller() -> None:
    global _poller_task
    if _poller_task is None:
        return
    _poller_task.cancel()
    try:
        await _poller_task
    except asyncio.CancelledError:
        pass
    _poller_task = None


async def api_history(request: Request):
    return JSONResponse(history.load())


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
            note_stop_sent()
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
    Route("/api/history", api_history, methods=["GET"]),
    Route("/api/settings", api_get_settings, methods=["GET"]),
    Route("/api/settings", api_set_settings, methods=["PUT"]),
    Mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static"),
]

app = Starlette(
    routes=routes,
    on_startup=[start_history_poller],
    on_shutdown=[stop_history_poller],
)
