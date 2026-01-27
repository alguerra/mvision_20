"""
Módulo de autodetecção da cama hospitalar.
Utiliza YOLOv8 para detectar a cama e persiste coordenadas para re-uso.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from config import (
    BED_CLASS_NAMES,
    BED_RECHECK_INTERVAL_HOURS,
    BED_REFERENCE_PATH,
)


class BedDetector:
    """Detector de cama hospitalar usando YOLOv8."""

    def __init__(self, yolo_model):
        """
        Inicializa o detector de cama.

        Args:
            yolo_model: Modelo YOLO carregado para inferência.
        """
        self.model = yolo_model
        self.bed_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_detection_time: Optional[float] = None
        self.reference_path = Path(BED_REFERENCE_PATH)
        self.detected_class_name: Optional[str] = None

        # Resolve nomes de classes para índices
        self.bed_class_indices = self._get_class_indices()

        # Tenta carregar referência salva
        self.load_reference()

    def _get_class_indices(self) -> list:
        """
        Resolve nomes de classes para índices usando model.names.

        Returns:
            Lista de índices correspondentes aos nomes em BED_CLASS_NAMES.
        """
        indices = []
        target_names = [n.lower() for n in BED_CLASS_NAMES]

        # model.names é um dict {0: 'person', 1: 'bicycle', ..., 59: 'bed', ...}
        for idx, name in self.model.names.items():
            if name.lower() in target_names:
                indices.append(idx)
                print(f"[BedDetector] Classe '{name}' mapeada para índice {idx}")

        if not indices:
            print(f"[BedDetector] AVISO: Nenhuma classe encontrada para {BED_CLASS_NAMES}")

        return indices

    def detect_bed(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Executa inferência buscando classes de cama no frame.

        Args:
            frame: Frame de vídeo (numpy array BGR).

        Returns:
            Tuple (x1, y1, x2, y2) com coordenadas da cama ou None se não detectada.
        """
        if not self.bed_class_indices:
            return None

        results = self.model.predict(frame, classes=self.bed_class_indices, verbose=False)

        if len(results) > 0 and len(results[0].boxes) > 0:
            # Pega a detecção com maior confiança
            boxes = results[0].boxes
            best_idx = boxes.conf.argmax()
            bbox = boxes.xyxy[best_idx].cpu().numpy().astype(int)

            # Guarda o nome da classe detectada
            class_id = int(boxes.cls[best_idx])
            self.detected_class_name = self.model.names[class_id]

            self.bed_bbox = tuple(bbox)
            self.last_detection_time = time.time()
            return self.bed_bbox

        return None

    def save_reference(self, bbox: Tuple[int, int, int, int]) -> None:
        """
        Persiste coordenadas da cama em arquivo JSON.

        Args:
            bbox: Tuple (x1, y1, x2, y2) com coordenadas.
        """
        self.reference_path.parent.mkdir(parents=True, exist_ok=True)

        # Converte numpy int64 para int nativo Python
        data = {
            "bbox": [int(v) for v in bbox],
            "timestamp": time.time(),
        }

        with open(self.reference_path, "w") as f:
            json.dump(data, f, indent=2)

        self.bed_bbox = bbox
        self.last_detection_time = data["timestamp"]

    def load_reference(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Carrega coordenadas salvas do arquivo JSON.

        Returns:
            Tuple com coordenadas ou None se arquivo não existir.
        """
        if not self.reference_path.exists():
            return None

        try:
            with open(self.reference_path, "r") as f:
                data = json.load(f)

            self.bed_bbox = tuple(data["bbox"])
            self.last_detection_time = data.get("timestamp", time.time())
            return self.bed_bbox

        except (json.JSONDecodeError, KeyError):
            return None

    def needs_recheck(self) -> bool:
        """
        Verifica se passou o intervalo de re-verificação.

        Returns:
            True se precisa re-verificar a cama.
        """
        if self.last_detection_time is None:
            return True

        elapsed_hours = (time.time() - self.last_detection_time) / 3600
        return elapsed_hours >= BED_RECHECK_INTERVAL_HOURS

    def get_bed_bbox(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Retorna bbox atual da cama.

        Returns:
            Tuple (x1, y1, x2, y2) ou None se não detectada.
        """
        return self.bed_bbox

    def has_valid_reference(self) -> bool:
        """
        Verifica se existe uma referência salva válida da cama.

        Returns:
            True se existe arquivo de referência salvo.
        """
        return self.reference_path.exists() and self.bed_bbox is not None

    def get_detected_class_name(self) -> str:
        """
        Retorna nome da classe que foi detectada como cama.

        Returns:
            Nome da classe detectada ou "N/A" se nenhuma detecção.
        """
        return self.detected_class_name or "N/A"
