"""
Configuration manager for MVision Web Interface.
Handles reading and writing device and system configurations.
"""

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
ENVIRONMENT_CONFIG_PATH = BASE_DIR / "config" / "environment.json"
SYSTEM_CONFIG_PATH = BASE_DIR / "config.py"
RUNTIME_CONFIG_PATH = BASE_DIR / "config" / "runtime_config.json"
SERVICE_NAME = "hospital-monitor"

# Permite importar modulos do projeto (escrita atomica e whitelist de chaves)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.atomic_io import atomic_write_json

# Chaves que o painel pode editar (espelha config.RUNTIME_EDITABLE_KEYS).
# IMPORTANTE: o painel NUNCA reescreve config.py — apenas o JSON de runtime.
try:
    from config import RUNTIME_EDITABLE_KEYS
except Exception:
    RUNTIME_EDITABLE_KEYS = [
        "FLIP_HORIZONTAL",
        "BED_RECHECK_INTERVAL_HOURS",
        "BED_DETECTION_SENSITIVITY",
        "EMA_ALPHA",
        "EMA_THRESHOLD_ENTER_RISK",
        "EMA_THRESHOLD_EXIT_RISK",
        "POSE_CONFIDENCE_HIGH",
        "POSE_FRAMES_TO_CONFIRM",
        "FRAMES_TO_LOSE_PATIENT",
        "COMPANION_ANALYSIS_ENABLED",
    ]


def get_environment_config() -> dict:
    """Load environment configuration."""
    if ENVIRONMENT_CONFIG_PATH.exists():
        with open(ENVIRONMENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "environment_id": "",
        "hospital": "",
        "sector": "",
        "bed": ""
    }


def save_environment_config(config: dict) -> tuple[bool, str]:
    """Save environment configuration."""
    try:
        ENVIRONMENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ENVIRONMENT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True, "Configuração salva com sucesso"
    except Exception as e:
        return False, f"Erro ao salvar configuração: {str(e)}"


def _read_runtime_overrides() -> dict:
    """Le overrides atuais do runtime_config.json (vazio se ausente/corrompido)."""
    try:
        if RUNTIME_CONFIG_PATH.exists():
            with open(RUNTIME_CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _read_config_defaults() -> dict:
    """
    Le os DEFAULTS do config.py por regex (somente leitura, nunca escreve).
    DEV_MODE/DEV_SKIP_BED_DETECTION vem de variavel de ambiente e sao
    reportados apenas informativamente.
    """
    settings = {
        "DEV_MODE": os.environ.get("MVISION_DEV", "0") == "1",
        "DEV_SKIP_BED_DETECTION": os.environ.get("MVISION_SKIP_BED", "0") == "1",
        "FLIP_HORIZONTAL": True,
        "BED_RECHECK_INTERVAL_HOURS": 6,
        "POSE_FRAMES_TO_CONFIRM": 10,
        "EMA_ALPHA": 0.3,
        "EMA_THRESHOLD_ENTER_RISK": 0.5,
        "EMA_THRESHOLD_EXIT_RISK": 0.3,
        "BED_DETECTION_SENSITIVITY": 5,
        "POSE_CONFIDENCE_HIGH": 0.7,
        "FRAMES_TO_LOSE_PATIENT": 15,
        "COMPANION_ANALYSIS_ENABLED": True,
    }

    if not SYSTEM_CONFIG_PATH.exists():
        return settings

    try:
        with open(SYSTEM_CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        for key in ["FLIP_HORIZONTAL", "COMPANION_ANALYSIS_ENABLED"]:
            match = re.search(rf'^{key}\s*=\s*(True|False)', content, re.MULTILINE)
            if match:
                settings[key] = match.group(1) == "True"

        for key in ["BED_RECHECK_INTERVAL_HOURS", "POSE_FRAMES_TO_CONFIRM",
                    "BED_DETECTION_SENSITIVITY", "FRAMES_TO_LOSE_PATIENT"]:
            match = re.search(rf'^{key}\s*=\s*(\d+)', content, re.MULTILINE)
            if match:
                settings[key] = int(match.group(1))

        for key in ["EMA_ALPHA", "EMA_THRESHOLD_ENTER_RISK",
                    "EMA_THRESHOLD_EXIT_RISK", "POSE_CONFIDENCE_HIGH"]:
            match = re.search(rf'^{key}\s*=\s*([\d.]+)', content, re.MULTILINE)
            if match:
                settings[key] = float(match.group(1))

    except Exception:
        pass

    return settings


def get_system_settings() -> dict:
    """Configuracoes efetivas: defaults do config.py + overlay do runtime json."""
    settings = _read_config_defaults()
    overrides = _read_runtime_overrides()
    for key, value in overrides.items():
        if key in settings:
            settings[key] = value
    return settings


def save_system_settings(settings: dict) -> tuple:
    """
    Persiste configuracoes editaveis em config/runtime_config.json (escrita
    ATOMICA — um corte de energia nunca corrompe a configuracao nem impede
    o boot; o config.py nao e mais tocado pelo painel).
    """
    try:
        # Valida e filtra pela whitelist
        current = _read_runtime_overrides()
        rejected = []
        for key, value in settings.items():
            if key not in RUNTIME_EDITABLE_KEYS:
                # DEV_MODE etc.: apenas via variavel de ambiente
                if key not in ("DEV_MODE", "DEV_SKIP_BED_DETECTION"):
                    rejected.append(key)
                continue
            if not isinstance(value, (bool, int, float, str)):
                rejected.append(key)
                continue
            current[key] = value

        atomic_write_json(RUNTIME_CONFIG_PATH, current)

        message = "Configurações salvas com sucesso"
        if rejected:
            message += f" (ignoradas: {', '.join(rejected)})"
        message += ". Reinicie o serviço para aplicar."
        return True, message
    except Exception as e:
        return False, f"Erro ao salvar configurações: {str(e)}"


def get_system_info() -> dict:
    """Get system information (IP, hostname, etc.)."""
    info = {
        "hostname": socket.gethostname(),
        "ip_addresses": [],
        "platform": "unknown"
    }

    # Get IP addresses — SEM referencia externa (sistema offline):
    # enumera interfaces locais via hostname/getaddrinfo e `hostname -I`
    try:
        host_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        info["ip_addresses"].extend(
            ip for ip in host_ips if not ip.startswith("127.")
        )
    except Exception:
        pass

    if not info["ip_addresses"]:
        try:
            result = subprocess.run(
                ["hostname", "-I"], capture_output=True, text=True, timeout=5
            )
            info["ip_addresses"].extend(
                ip for ip in result.stdout.split() if not ip.startswith("127.")
            )
        except Exception:
            pass

    # Detect platform
    try:
        import platform
        info["platform"] = platform.system().lower()
        if info["platform"] == "linux":
            # Check if Raspberry Pi
            try:
                with open("/proc/device-tree/model", "r") as f:
                    model = f.read()
                    if "raspberry" in model.lower():
                        info["platform"] = "raspberry_pi"
                        info["model"] = model.strip()
            except Exception:
                pass
    except Exception:
        pass

    return info


def get_service_status() -> dict:
    """Get the status of the main monitoring service."""
    status = {
        "running": False,
        "enabled": False,
        "status": "unknown"
    }

    try:
        # Check if systemctl is available (Linux only)
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=5
        )
        status["status"] = result.stdout.strip()
        status["running"] = result.returncode == 0

        # Check if enabled
        result = subprocess.run(
            ["systemctl", "is-enabled", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=5
        )
        status["enabled"] = result.returncode == 0

    except FileNotFoundError:
        status["status"] = "systemctl not available"
    except subprocess.TimeoutExpired:
        status["status"] = "timeout"
    except Exception as e:
        status["status"] = str(e)

    return status


def restart_service() -> tuple[bool, str]:
    """Restart the main monitoring service."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, "Serviço reiniciado com sucesso"
        else:
            return False, f"Erro ao reiniciar: {result.stderr}"
    except FileNotFoundError:
        return False, "systemctl não disponível"
    except subprocess.TimeoutExpired:
        return False, "Timeout ao reiniciar serviço"
    except Exception as e:
        return False, str(e)
