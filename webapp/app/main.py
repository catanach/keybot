from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import storage, flatten, device, settings

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
    return JSONResponse({"ok": True})


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
    Route("/api/settings", api_get_settings, methods=["GET"]),
    Route("/api/settings", api_set_settings, methods=["PUT"]),
    Mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static"),
]

app = Starlette(routes=routes)
