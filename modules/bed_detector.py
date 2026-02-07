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

    def _calculate_bed_score(
        self,
        bbox: np.ndarray,
        frame_height: int,
        frame_width: int,
        confidence: float,
    ) -> float:
        """
        Calcula score para selecionar a cama principal no campo de visão.

        Prioriza camas que estão:
        - Mais centralizadas no frame
        - Ocupam maior área (mais visíveis)
        - Não estão cortadas nas bordas

        Args:
            bbox: Coordenadas (x1, y1, x2, y2) da detecção.
            frame_height: Altura do frame.
            frame_width: Largura do frame.
            confidence: Score de confiança do YOLO.

        Returns:
            Score combinado (maior = melhor candidata).
        """
        x1, y1, x2, y2 = bbox

        # 1. Score de área - camas mais visíveis ocupam mais espaço
        bed_area = (x2 - x1) * (y2 - y1)
        frame_area = frame_width * frame_height
        area_score = bed_area / frame_area  # Normalizado 0-1

        # 2. Score de centralização - camas no centro do campo de visão
        bed_center_x = (x1 + x2) / 2
        bed_center_y = (y1 + y2) / 2
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2

        # Distância normalizada do centro (0 = centro perfeito, 1 = canto)
        dist_x = abs(bed_center_x - frame_center_x) / (frame_width / 2)
        dist_y = abs(bed_center_y - frame_center_y) / (frame_height / 2)
        center_distance = (dist_x + dist_y) / 2
        center_score = 1 - center_distance  # Invertido: mais perto do centro = maior score

        # 3. Penalidade para camas cortadas nas bordas
        edge_margin = 5  # pixels de margem para considerar "na borda"
        edge_penalty = 0.0

        if x1 <= edge_margin:  # Cortada na esquerda
            edge_penalty += 0.3
        if y1 <= edge_margin:  # Cortada em cima
            edge_penalty += 0.3
        if x2 >= frame_width - edge_margin:  # Cortada na direita
            edge_penalty += 0.3
        if y2 >= frame_height - edge_margin:  # Cortada embaixo
            edge_penalty += 0.3

        # Score final: combinação ponderada
        # - Área tem peso maior (cama principal geralmente é a maior e mais visível)
        # - Centralização ajuda a desempatar
        # - Confiança do YOLO ainda é considerada
        # - Penalidade forte para camas parcialmente visíveis
        final_score = (
            area_score * 0.45 +
            center_score * 0.30 +
            confidence * 0.25
        ) * (1 - edge_penalty)

        return final_score

    def detect_bed(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Executa inferência buscando classes de cama no frame.

        Quando múltiplas camas são detectadas, seleciona a mais adequada
        baseando-se em área, centralização e visibilidade completa no frame.

        Args:
            frame: Frame de vídeo (numpy array BGR).

        Returns:
            Tuple (x1, y1, x2, y2) com coordenadas da cama ou None se não detectada.
        """
        if not self.bed_class_indices:
            return None

        results = self.model.predict(frame, classes=self.bed_class_indices, verbose=False)

        if len(results) > 0 and len(results[0].boxes) > 0:
            boxes = results[0].boxes
            frame_height, frame_width = frame.shape[:2]

            # Calcula score para cada cama detectada
            best_score = -1
            best_idx = 0

            for i in range(len(boxes)):
                bbox = boxes.xyxy[i].cpu().numpy()
                confidence = float(boxes.conf[i])

                score = self._calculate_bed_score(
                    bbox, frame_height, frame_width, confidence
                )

                if score > best_score:
                    best_score = score
                    best_idx = i

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

    def postpone_recheck(self) -> None:
        """Adia proximo recheck atualizando timestamp para agora."""
        self.last_detection_time = time.time()

    def is_bbox_consistent(
        self,
        new_bbox: Tuple[int, int, int, int],
        min_iou: float = 0.3,
    ) -> bool:
        """
        Verifica se novo bbox e consistente com o atual (IoU minimo).

        Protege contra deteccoes espurias que substituiriam a
        calibracao valida (ex: pessoa ou objeto detectado como cama).

        Args:
            new_bbox: Novo bbox candidato (x1, y1, x2, y2).
            min_iou: IoU minimo para considerar consistente.

        Returns:
            True se bbox e consistente ou nao ha referencia anterior.
        """
        if self.bed_bbox is None:
            return True

        ax1, ay1, ax2, ay2 = self.bed_bbox
        bx1, by1, bx2, by2 = new_bbox

        # Calcula intersecao
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        if ix1 >= ix2 or iy1 >= iy2:
            return False

        intersection = (ix2 - ix1) * (iy2 - iy1)
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        union = area_a + area_b - intersection

        if union <= 0:
            return False

        iou = intersection / union
        return iou >= min_iou

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
