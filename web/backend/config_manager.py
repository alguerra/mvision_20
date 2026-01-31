"""
Configuration manager for MVision Web Interface.
Handles reading and writing device and system configurations.
"""

import json
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Any, Optional

# Paths
BASE_DIR = Path(__file__).parent.parent.parent
ENVIRONMENT_CONFIG_PATH = BASE_DIR / "config" / "environment.json"
SYSTEM_CONFIG_PATH = BASE_DIR / "config.py"
SERVICE_NAME = "hospital-monitor"


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


def get_system_settings() -> dict:
    """
    Read system settings from config.py.
    Returns a dict with key settings.
    """
    settings = {
        "DEV_MODE": False,
        "DEV_SKIP_BED_DETECTION": False,
        "FLIP_HORIZONTAL": True,
        "BED_RECHECK_INTERVAL_HOURS": 6,
        "POSE_FRAMES_TO_CONFIRM": 10,
        "EMA_ALPHA": 0.3,
        "EMA_THRESHOLD_ENTER_RISK": 0.5,
        "EMA_THRESHOLD_EXIT_RISK": 0.3,
    }

    if not SYSTEM_CONFIG_PATH.exists():
        return settings

    try:
        with open(SYSTEM_CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse boolean settings
        for key in ["DEV_MODE", "DEV_SKIP_BED_DETECTION", "FLIP_HORIZONTAL"]:
            match = re.search(rf'^{key}\s*=\s*(True|False)', content, re.MULTILINE)
            if match:
                settings[key] = match.group(1) == "True"

        # Parse numeric settings
        for key in ["BED_RECHECK_INTERVAL_HOURS", "POSE_FRAMES_TO_CONFIRM"]:
            match = re.search(rf'^{key}\s*=\s*(\d+)', content, re.MULTILINE)
            if match:
                settings[key] = int(match.group(1))

        # Parse float settings
        for key in ["EMA_ALPHA", "EMA_THRESHOLD_ENTER_RISK", "EMA_THRESHOLD_EXIT_RISK"]:
            match = re.search(rf'^{key}\s*=\s*([\d.]+)', content, re.MULTILINE)
            if match:
                settings[key] = float(match.group(1))

    except Exception:
        pass

    return settings


def save_system_settings(settings: dict) -> tuple[bool, str]:
    """
    Update system settings in config.py.
    Only updates specified keys, preserves the rest.
    """
    if not SYSTEM_CONFIG_PATH.exists():
        return False, "Arquivo config.py não encontrado"

    try:
        with open(SYSTEM_CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Update boolean settings
        for key in ["DEV_MODE", "DEV_SKIP_BED_DETECTION", "FLIP_HORIZONTAL"]:
            if key in settings:
                value = "True" if settings[key] else "False"
                content = re.sub(
                    rf'^({key}\s*=\s*)(True|False)',
                    rf'\g<1>{value}',
                    content,
                    flags=re.MULTILINE
                )

        # Update integer settings
        for key in ["BED_RECHECK_INTERVAL_HOURS", "POSE_FRAMES_TO_CONFIRM"]:
            if key in settings:
                value = int(settings[key])
                content = re.sub(
                    rf'^({key}\s*=\s*)\d+',
                    rf'\g<1>{value}',
                    content,
                    flags=re.MULTILINE
                )

        # Update float settings
        for key in ["EMA_ALPHA", "EMA_THRESHOLD_ENTER_RISK", "EMA_THRESHOLD_EXIT_RISK"]:
            if key in settings:
                value = float(settings[key])
                content = re.sub(
                    rf'^({key}\s*=\s*)[\d.]+',
                    rf'\g<1>{value}',
                    content,
                    flags=re.MULTILINE
                )

        with open(SYSTEM_CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        return True, "Configurações salvas com sucesso"
    except Exception as e:
        return False, f"Erro ao salvar configurações: {str(e)}"


def get_system_info() -> dict:
    """Get system information (IP, hostname, etc.)."""
    info = {
        "hostname": socket.gethostname(),
        "ip_addresses": [],
        "platform": "unknown"
    }

    # Get IP addresses
    try:
        # Try to get the main IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info["ip_addresses"].append(s.getsockname()[0])
        s.close()
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
