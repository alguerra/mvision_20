"""
Modulo de log de alertas com rotacao e retencao de imagens.

Registra eventos de alerta em arquivo de log rotacionado e salva
imagens de evidencia quando em modo de desenvolvimento/homologacao.

Formato do log:
    2026-01-26 21:49:34 | UTI-LEITO-12 | WARNING | ALERTA | RISCO_POTENCIAL | Detalhes
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import (
    ALERT_IMAGES_DIR,
    ALERT_LOG_BACKUP_COUNT,
    ALERT_LOG_MAX_BYTES,
    ALERT_LOG_PATH,
    DEV_MODE,
    MAX_ALERT_IMAGES,
)
from modules.environment import get_environment_config


class AlertLogger:
    """Gerenciador de logs de alertas e imagens de evidencia."""

    def __init__(
        self,
        log_path: str = ALERT_LOG_PATH,
        images_dir: str = ALERT_IMAGES_DIR,
        max_images: int = MAX_ALERT_IMAGES,
        dev_mode: bool = DEV_MODE,
        max_bytes: int = ALERT_LOG_MAX_BYTES,
        backup_count: int = ALERT_LOG_BACKUP_COUNT,
    ):
        """
        Inicializa o logger de alertas.

        Args:
            log_path: Caminho para o arquivo de log
            images_dir: Diretorio para imagens de alertas
            max_images: Maximo de imagens a reter
            dev_mode: Se True, salva imagens de evidencia
            max_bytes: Tamanho maximo do arquivo de log antes de rotacionar
            backup_count: Numero de arquivos de backup a manter
        """
        self.log_path = log_path
        self.images_dir = images_dir
        self.max_images = max_images
        self.dev_mode = dev_mode

        # Carrega configuracao do ambiente
        env_config = get_environment_config()
        self.environment_id = env_config["environment_id"]
        self.hospital = env_config.get("hospital", "")
        self.sector = env_config.get("sector", "")
        self.bed = env_config.get("bed", "")

        # Cria diretorios se nao existem
        self._ensure_directories()

        # Configura logger rotacionado
        self.logger = self._setup_logger(max_bytes, backup_count)

        # Contador de alertas
        self.alert_count = 0

    def _ensure_directories(self) -> None:
        """Cria diretorios necessarios se nao existem."""
        # Diretorio do log
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)

        # Diretorio de imagens
        if self.dev_mode:
            Path(self.images_dir).mkdir(parents=True, exist_ok=True)

    def _setup_logger(self, max_bytes: int, backup_count: int) -> logging.Logger:
        """
        Configura logger com handler rotacionado.

        Args:
            max_bytes: Tamanho maximo do arquivo antes de rotacionar
            backup_count: Numero de backups a manter

        Returns:
            Logger configurado
        """
        logger = logging.getLogger("AlertLogger")
        logger.setLevel(logging.INFO)

        # Remove handlers existentes para evitar duplicacao
        logger.handlers.clear()

        # Handler rotacionado
        handler = RotatingFileHandler(
            self.log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )

        # Formato do log com dados do dispositivo
        # Formato: 2026-01-26 21:49:34 | ID | Hospital | Setor | Leito | LEVEL | mensagem
        device_info = f"{self.environment_id} | {self.hospital} | {self.sector} | {self.bed}"
        formatter = logging.Formatter(
            f"%(asctime)s | {device_info} | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

        return logger

    def log_alert(
        self,
        pose_state: str,
        frame: Optional[np.ndarray] = None,
        details: Optional[str] = None,
    ) -> str:
        """
        Registra um alerta no log e opcionalmente salva imagem.

        Args:
            pose_state: Estado de pose do alerta (ex: RISCO_POTENCIAL, PACIENTE_FORA)
            frame: Frame de video para salvar como evidencia (se dev_mode)
            details: Detalhes adicionais do alerta

        Returns:
            Caminho da imagem salva ou string vazia se nao salvou
        """
        self.alert_count += 1
        timestamp = datetime.now()

        # Monta mensagem de log estruturada
        # Formato: ALERTA | ESTADO | Detalhes
        message = f"ALERTA | {pose_state}"
        if details:
            message += f" | {details}"

        # Registra no log
        self.logger.warning(message)

        # Salva imagem se em modo dev e frame fornecido
        image_path = ""
        if self.dev_mode and frame is not None:
            image_path = self._save_alert_image(frame, pose_state, timestamp)
            if image_path:
                self.logger.info(f"SISTEMA | IMAGEM_SALVA | {image_path}")

        return image_path

    def log_state_change(
        self,
        previous_state: str,
        new_state: str,
        frame: Optional[np.ndarray] = None,
    ) -> str:
        """
        Registra mudanca de estado.

        Args:
            previous_state: Estado anterior
            new_state: Novo estado
            frame: Frame de video para salvar como evidencia

        Returns:
            Caminho da imagem salva ou string vazia
        """
        details = f"Transicao: {previous_state} -> {new_state}"

        # Determina se eh um alerta
        alert_states = ["RISCO_POTENCIAL", "PACIENTE_FORA"]

        if new_state in alert_states:
            return self.log_alert(new_state, frame, details)
        else:
            # Loga transicao normal
            # Formato: TRANSICAO | NOVO_ESTADO | Detalhes
            self.logger.info(f"TRANSICAO | {new_state} | {details}")
            return ""

    def log_info(self, message: str) -> None:
        """Registra mensagem informativa no log."""
        self.logger.info(f"SISTEMA | INFO | {message}")

    def get_environment_id(self) -> str:
        """Retorna ID do ambiente configurado."""
        return self.environment_id

    def _save_alert_image(
        self,
        frame: np.ndarray,
        pose_state: str,
        timestamp: datetime,
    ) -> str:
        """
        Salva imagem de alerta com retencao.

        Args:
            frame: Frame de video
            pose_state: Estado de pose
            timestamp: Data/hora do alerta

        Returns:
            Caminho da imagem salva ou string vazia se falhou
        """
        # Garante que diretorio existe
        Path(self.images_dir).mkdir(parents=True, exist_ok=True)

        # Aplica retencao antes de salvar
        self._apply_retention()

        # Gera nome do arquivo
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Remove ultimos 3 digitos do microsegundo
        filename = f"alert_{timestamp_str}_{pose_state}.jpg"
        filepath = os.path.join(self.images_dir, filename)

        # Salva imagem
        try:
            cv2.imwrite(filepath, frame)
            return filepath
        except Exception as e:
            self.logger.error(f"Erro ao salvar imagem: {e}")
            return ""

    def _apply_retention(self) -> None:
        """
        Aplica politica de retencao de imagens.

        Remove imagens mais antigas se exceder o limite maximo.
        """
        try:
            images_path = Path(self.images_dir)

            # Lista imagens existentes ordenadas por data de modificacao
            images = sorted(
                images_path.glob("alert_*.jpg"),
                key=lambda x: x.stat().st_mtime,
            )

            # Remove imagens mais antigas se exceder limite
            # (max_images - 1 para dar espaco para a nova imagem)
            while len(images) >= self.max_images:
                oldest = images.pop(0)
                oldest.unlink()
                self.logger.info(f"Imagem removida por retencao: {oldest.name}")

        except Exception as e:
            self.logger.error(f"Erro ao aplicar retencao: {e}")

    def get_alert_count(self) -> int:
        """Retorna contagem de alertas registrados."""
        return self.alert_count

    def get_image_count(self) -> int:
        """Retorna quantidade de imagens no diretorio."""
        try:
            images_path = Path(self.images_dir)
            return len(list(images_path.glob("alert_*.jpg")))
        except Exception:
            return 0
