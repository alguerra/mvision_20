"""
Modulo de identificacao de ambiente para deploy em multiplos dispositivos.

Carrega ID do ambiente de arquivo de configuracao JSON ou texto,
com fallback para hostname da maquina.
"""

import json
import socket
from pathlib import Path
from typing import Optional

from config import (
    ENVIRONMENT_CONFIG_PATH,
    ENVIRONMENT_DEFAULT_ID,
)


def get_environment_id() -> str:
    """
    Carrega ID do ambiente na seguinte ordem de prioridade:

    1. Arquivo JSON em ENVIRONMENT_CONFIG_PATH (campo "environment_id")
    2. Hostname da maquina
    3. ENVIRONMENT_DEFAULT_ID (fallback final)

    Returns:
        String com ID do ambiente
    """
    # 1. Tenta arquivo JSON
    env_id = _load_from_json(ENVIRONMENT_CONFIG_PATH)
    if env_id:
        return env_id

    # 2. Tenta hostname
    env_id = _get_hostname()
    if env_id:
        return env_id

    # 3. Fallback final
    return ENVIRONMENT_DEFAULT_ID


def _load_from_json(path: str) -> Optional[str]:
    """
    Carrega environment_id de arquivo JSON.

    Args:
        path: Caminho para arquivo JSON

    Returns:
        environment_id ou None se nao encontrado
    """
    try:
        config_path = Path(path)
        if not config_path.exists():
            return None

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        env_id = config.get("environment_id", "").strip()
        return env_id if env_id else None

    except (json.JSONDecodeError, OSError, KeyError):
        return None


def _get_hostname() -> Optional[str]:
    """
    Obtem hostname da maquina.

    Returns:
        Hostname ou None se erro
    """
    try:
        hostname = socket.gethostname()
        return hostname if hostname else None
    except OSError:
        return None


def get_environment_config() -> dict:
    """
    Carrega configuracao completa do ambiente.

    Returns:
        Dict com configuracao. Campos possiveis:
        - environment_id: ID do ambiente
        - hospital: Nome do hospital
        - sector: Setor (UTI, enfermaria, etc)
        - bed: Numero do leito
    """
    config = {
        "environment_id": get_environment_id(),
        "hospital": "",
        "sector": "",
        "bed": "",
    }

    # Tenta carregar config completa do JSON
    try:
        config_path = Path(ENVIRONMENT_CONFIG_PATH)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                json_config = json.load(f)

            # Atualiza campos se existirem
            for key in ["hospital", "sector", "bed"]:
                if key in json_config:
                    config[key] = json_config[key]

    except (json.JSONDecodeError, OSError):
        pass

    return config
