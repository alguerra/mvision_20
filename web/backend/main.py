"""
MVision Web Configuration Interface - FastAPI Backend
Serves the web interface and provides API endpoints for configuration.
"""

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import os

from auth import (
    init_auth,
    verify_password,
    change_password,
    create_session,
    verify_session,
    invalidate_session,
)
from config_manager import (
    get_environment_config,
    save_environment_config,
    get_system_settings,
    save_system_settings,
    get_system_info,
    get_service_status,
    restart_service,
)

# Initialize FastAPI
app = FastAPI(
    title="MVision Web Interface",
    description="Interface de configuração do MVision",
    version="1.0.0"
)

# Static files path
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "out"

# Session cookie name
SESSION_COOKIE = "mvision_session"


# ============== Pydantic Models ==============

class LoginRequest(BaseModel):
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class EnvironmentConfig(BaseModel):
    environment_id: str
    hospital: str
    sector: str
    bed: str


class SystemSettings(BaseModel):
    DEV_MODE: Optional[bool] = None
    DEV_SKIP_BED_DETECTION: Optional[bool] = None
    FLIP_HORIZONTAL: Optional[bool] = None
    BED_RECHECK_INTERVAL_HOURS: Optional[int] = None
    POSE_FRAMES_TO_CONFIRM: Optional[int] = None
    EMA_ALPHA: Optional[float] = None
    EMA_THRESHOLD_ENTER_RISK: Optional[float] = None
    EMA_THRESHOLD_EXIT_RISK: Optional[float] = None


# ============== Dependencies ==============

def get_session_token(request: Request) -> Optional[str]:
    """Extract session token from cookie."""
    return request.cookies.get(SESSION_COOKIE)


def require_auth(request: Request):
    """Dependency that requires authentication."""
    token = get_session_token(request)
    if not verify_session(token):
        raise HTTPException(status_code=401, detail="Não autenticado")
    return token


# ============== Auth Endpoints ==============

@app.post("/api/auth/login")
async def login(request: LoginRequest, response: Response):
    """Login with password."""
    if verify_password(request.password):
        token = create_session()
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            httponly=True,
            max_age=86400,  # 24 hours
            samesite="lax"
        )
        return {"success": True, "message": "Login realizado com sucesso"}
    else:
        raise HTTPException(status_code=401, detail="Senha incorreta")


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    """Logout and invalidate session."""
    token = get_session_token(request)
    if token:
        invalidate_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"success": True, "message": "Logout realizado"}


@app.get("/api/auth/check")
async def check_auth(request: Request):
    """Check if current session is valid."""
    token = get_session_token(request)
    is_authenticated = verify_session(token)
    return {"authenticated": is_authenticated}


@app.post("/api/auth/password")
async def update_password(
    request: PasswordChangeRequest,
    _: str = Depends(require_auth)
):
    """Change password."""
    success, message = change_password(request.current_password, request.new_password)
    if success:
        return {"success": True, "message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


# ============== Config Endpoints ==============

@app.get("/api/config")
async def get_config(_: str = Depends(require_auth)):
    """Get device configuration."""
    return get_environment_config()


@app.post("/api/config")
async def update_config(
    config: EnvironmentConfig,
    _: str = Depends(require_auth)
):
    """Save device configuration."""
    success, message = save_environment_config(config.model_dump())
    if success:
        return {"success": True, "message": message}
    else:
        raise HTTPException(status_code=500, detail=message)


# ============== Settings Endpoints ==============

@app.get("/api/settings")
async def get_settings(_: str = Depends(require_auth)):
    """Get system settings."""
    return get_system_settings()


@app.post("/api/settings")
async def update_settings(
    settings: SystemSettings,
    _: str = Depends(require_auth)
):
    """Update system settings."""
    # Filter out None values
    settings_dict = {k: v for k, v in settings.model_dump().items() if v is not None}
    success, message = save_system_settings(settings_dict)
    if success:
        return {"success": True, "message": message}
    else:
        raise HTTPException(status_code=500, detail=message)


# ============== System Endpoints ==============

@app.get("/api/system/info")
async def system_info(_: str = Depends(require_auth)):
    """Get system information."""
    return get_system_info()


@app.get("/api/system/status")
async def system_status(_: str = Depends(require_auth)):
    """Get service status."""
    return get_service_status()


@app.post("/api/system/restart")
async def system_restart(_: str = Depends(require_auth)):
    """Restart the monitoring service."""
    success, message = restart_service()
    if success:
        return {"success": True, "message": message}
    else:
        raise HTTPException(status_code=500, detail=message)


# ============== Static Files ==============

# Serve static files from the frontend build
if FRONTEND_DIR.exists():
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve frontend static files."""
        # Try exact file first
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # Try with .html extension
        html_path = FRONTEND_DIR / f"{full_path}.html"
        if html_path.is_file():
            return FileResponse(html_path)

        # For SPA routing, serve index.html
        index_path = FRONTEND_DIR / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)

        # 404
        raise HTTPException(status_code=404, detail="Not found")


# ============== Startup ==============

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    init_auth()
    print("MVision Web Interface started")
    print(f"Frontend directory: {FRONTEND_DIR}")
    print(f"Frontend exists: {FRONTEND_DIR.exists()}")


# ============== Main ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
