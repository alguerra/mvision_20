"""
MVision Web Configuration Interface - FastAPI Backend
Serves the web interface and provides API endpoints for configuration.
"""

from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, List
import os
import re
from datetime import datetime

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

# Import config values for diagnostics
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import (
    DEV_MODE,
    ALERT_IMAGES_DIR,
    ALERT_LOG_PATH,
    ALERT_LOG_RETENTION_DAYS,
)

# Paths for diagnostics
PROJECT_ROOT = Path(__file__).parent.parent.parent
ALERT_IMAGES_PATH = PROJECT_ROOT / ALERT_IMAGES_DIR
LOGS_PATH = PROJECT_ROOT / "data" / "logs"

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


# ============== Diagnostics Endpoints ==============

@app.get("/api/diagnostics/images")
async def get_alert_images(_: str = Depends(require_auth)):
    """List alert images (DEV_MODE only)."""
    # Re-import to get current value
    from config import DEV_MODE as current_dev_mode

    if not current_dev_mode:
        return {
            "images": [],
            "total": 0,
            "dev_mode": False
        }

    images = []
    if ALERT_IMAGES_PATH.exists():
        for img_file in sorted(ALERT_IMAGES_PATH.glob("*.jpg"), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = img_file.stat()
            # Parse filename: alert_YYYYMMDD_HHMMSS_mmm_STATE.jpg
            filename = img_file.name
            state = "DESCONHECIDO"
            timestamp = ""

            # Try to extract state and timestamp from filename
            # Format: alert_20260126_212333_132_RISCO_POTENCIAL.jpg
            if "_RISCO_POTENCIAL" in filename:
                state = "RISCO_POTENCIAL"
            elif "_PACIENTE_FORA" in filename:
                state = "PACIENTE_FORA"

            # Extract timestamp (YYYYMMDD_HHMMSS)
            match = re.search(r'alert_(\d{8}_\d{6})', filename)
            if match:
                timestamp = match.group(1)

            images.append({
                "filename": filename,
                "timestamp": timestamp,
                "state": state,
                "size_kb": round(stat.st_size / 1024, 1)
            })

    return {
        "images": images,
        "total": len(images),
        "dev_mode": True
    }


@app.get("/api/diagnostics/images/{filename}")
async def get_alert_image(filename: str, _: str = Depends(require_auth)):
    """Serve individual alert image (DEV_MODE only)."""
    # Re-import to get current value
    from config import DEV_MODE as current_dev_mode

    if not current_dev_mode:
        raise HTTPException(status_code=403, detail="DEV_MODE desabilitado")

    # Security: validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")

    if not filename.endswith(".jpg"):
        raise HTTPException(status_code=400, detail="Somente arquivos .jpg permitidos")

    file_path = ALERT_IMAGES_PATH / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    return FileResponse(file_path, media_type="image/jpeg")


@app.get("/api/diagnostics/logs/files")
async def get_log_files(_: str = Depends(require_auth)):
    """List available log files."""
    files = []

    if LOGS_PATH.exists():
        # Main log file
        main_log = LOGS_PATH / "alerts.log"
        if main_log.exists():
            stat = main_log.stat()
            files.append({
                "filename": "alerts.log",
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

        # Backup files (date-based: alerts.log.2024-01-15)
        for log_file in sorted(LOGS_PATH.glob("alerts.log.*"), reverse=True):
            # Skip non-date suffixes
            suffix = log_file.name.replace("alerts.log.", "")
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', suffix):
                continue
            stat = log_file.stat()
            files.append({
                "filename": log_file.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

    return {"files": files}


@app.get("/api/diagnostics/logs")
async def get_logs(
    file: str = Query(default="alerts.log", description="Nome do arquivo de log"),
    level: Optional[str] = Query(default=None, description="Filtrar por nível (INFO, WARNING, ERROR)"),
    category: Optional[str] = Query(default=None, description="Filtrar por categoria (SISTEMA, TRANSICAO, ALERTA)"),
    search: Optional[str] = Query(default=None, description="Busca texto livre"),
    limit: int = Query(default=50, ge=1, le=200, description="Limite de entradas"),
    offset: int = Query(default=0, ge=0, description="Offset para paginação"),
    _: str = Depends(require_auth)
):
    """Get logs with filters and pagination."""
    # Security: validate filename (alerts.log or alerts.log.YYYY-MM-DD)
    if file != "alerts.log":
        if not file.startswith("alerts.log."):
            raise HTTPException(status_code=400, detail="Arquivo de log inválido")
        suffix = file.replace("alerts.log.", "")
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', suffix):
            raise HTTPException(status_code=400, detail="Arquivo de log inválido")

    # Build list of available files dynamically
    available_files = ["alerts.log"]
    if LOGS_PATH.exists():
        for log_file in sorted(LOGS_PATH.glob("alerts.log.*"), reverse=True):
            suffix = log_file.name.replace("alerts.log.", "")
            if re.match(r'^\d{4}-\d{2}-\d{2}$', suffix):
                available_files.append(log_file.name)

    file_path = LOGS_PATH / file
    if not file_path.exists():
        return {
            "entries": [],
            "total_lines": 0,
            "file_name": file,
            "available_files": available_files
        }

    # Log pattern: 2026-01-26 21:22:25 | INFO | Mensagem aqui
    # ou com device info: 2026-01-26 21:22:25 | ENV | HOSP | SETOR | LEITO | INFO | Mensagem
    log_pattern = re.compile(
        r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(?:[^|]+\s*\|\s*)?(?:[^|]+\s*\|\s*)?(?:[^|]+\s*\|\s*)?(?:[^|]+\s*\|\s*)?(INFO|WARNING|ERROR)\s*\|\s*(.*)$'
    )

    entries = []
    total_lines = 0

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

        for line_num, line in enumerate(all_lines, 1):
            line = line.strip()
            if not line:
                continue

            match = log_pattern.match(line)
            if match:
                timestamp, log_level, details = match.groups()

                # Extract category from message content
                if "ALERTA" in details:
                    log_category = "ALERTA"
                elif "Transicao" in details or "transicao" in details:
                    log_category = "TRANSICAO"
                else:
                    log_category = "SISTEMA"

                # Apply filters
                if level and log_level != level:
                    continue
                if category and log_category != category:
                    continue
                if search and search.lower() not in line.lower():
                    continue

                entries.append({
                    "line_number": line_num,
                    "timestamp": timestamp,
                    "level": log_level,
                    "category": log_category,
                    "details": details
                })
            else:
                # Non-matching line (continuation or malformed)
                if search and search.lower() not in line.lower():
                    continue
                entries.append({
                    "line_number": line_num,
                    "timestamp": "",
                    "level": "INFO",
                    "category": "RAW",
                    "details": line
                })

        total_lines = len(entries)
        # Apply pagination
        entries = entries[offset:offset + limit]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo: {str(e)}")

    return {
        "entries": entries,
        "total_lines": total_lines,
        "file_name": file,
        "available_files": available_files
    }


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
