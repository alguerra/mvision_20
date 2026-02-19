"""
Módulo de autodetecção da cama hospitalar.
Utiliza YOLOv8 com detecção multi-estratégia e persiste coordenadas para re-uso.

Estratégias de detecção (em ordem de prioridade):
  1. Primary: classes "bed", "couch" com confiança >= 0.25
  2. Secondary: classes "bed", "couch", "bench" com confiança >= 0.15
  3. Exploratory: mesmas classes com confiança >= 0.10 (apenas diagnóstico, não retorna)
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import (
    BED_CLASS_NAMES,
    BED_CLASS_NAMES_PRIMARY,
    BED_CLASS_NAMES_SECONDARY,
    BED_DETECTION_CONF_FALLBACK,
    BED_DETECTION_CONF_PRIMARY,
    BED_DETECTION_CONF_SECONDARY,
    BED_DETECTION_DIAGNOSTIC,
    BED_MIN_AREA_RATIO,
    BED_RECHECK_INTERVAL_HOURS,
    BED_REFERENCE_PATH,
)


class BedDetector:
    """Detector de cama hospitalar usando YOLOv8 com múltiplas estratégias."""

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
        self.detected_strategy: Optional[str] = None

        # Resolve nomes de classes para índices (legado, para recheck)
        self.bed_class_indices = self._resolve_class_names(BED_CLASS_NAMES)

        # Constrói estratégias de detecção
        self.strategies = self._build_strategies()

        # Tenta carregar referência salva
        self.load_reference()

    def _resolve_class_names(self, class_names: list) -> list:
        """
        Resolve nomes de classes para índices usando model.names.

        Args:
            class_names: Lista de nomes de classes a resolver.

        Returns:
            Lista de índices correspondentes aos nomes fornecidos.
        """
        indices = []
        target_names = [n.lower() for n in class_names]

        # model.names é um dict {0: 'person', 1: 'bicycle', ..., 59: 'bed', ...}
        for idx, name in self.model.names.items():
            if name.lower() in target_names:
                indices.append(idx)

        return indices

    def _build_strategies(self) -> List[Dict]:
        """
        Constrói lista ordenada de estratégias de detecção.

        Cada estratégia tem: nome, índices de classe, threshold de confiança,
        e flag indicando se retorna detecção ou apenas loga.

        Returns:
            Lista de dicts com estratégias ordenadas por prioridade.
        """
        strategies = []

        # Estratégia 1: Primary (bed, couch)
        primary_indices = self._resolve_class_names(BED_CLASS_NAMES_PRIMARY)
        if primary_indices:
            strategies.append({
                "name": "primary",
                "class_names": BED_CLASS_NAMES_PRIMARY,
                "class_indices": primary_indices,
                "conf": BED_DETECTION_CONF_PRIMARY,
                "returns_detection": True,
            })

        # Estratégia 2: Secondary (bed, couch, bench)
        secondary_indices = self._resolve_class_names(BED_CLASS_NAMES_SECONDARY)
        if secondary_indices:
            strategies.append({
                "name": "secondary",
                "class_names": BED_CLASS_NAMES_SECONDARY,
                "class_indices": secondary_indices,
                "conf": BED_DETECTION_CONF_SECONDARY,
                "returns_detection": True,
            })

        # Estratégia 3: Exploratory (apenas diagnóstico)
        exploratory_indices = self._resolve_class_names(BED_CLASS_NAMES_SECONDARY)
        if exploratory_indices:
            strategies.append({
                "name": "exploratory",
                "class_names": BED_CLASS_NAMES_SECONDARY,
                "class_indices": exploratory_indices,
                "conf": BED_DETECTION_CONF_FALLBACK,
                "returns_detection": False,
            })

        # Log das estratégias configuradas
        for s in strategies:
            names_str = ", ".join(s["class_names"])
            indices_str = ", ".join(str(i) for i in s["class_indices"])
            print(f"[BedDetector] Estrategia '{s['name']}': classes=[{names_str}] "
                  f"indices=[{indices_str}] conf>={s['conf']} "
                  f"retorna={'sim' if s['returns_detection'] else 'nao (diagnostico)'}")

        return strategies

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
        final_score = (
            area_score * 0.45 +
            center_score * 0.30 +
            confidence * 0.25
        ) * (1 - edge_penalty)

        return final_score

    def _select_best_detection(
        self,
        boxes,
        frame_height: int,
        frame_width: int,
    ) -> Optional[Tuple[Tuple[int, int, int, int], str, float, float]]:
        """
        Filtra por área mínima e seleciona a melhor detecção.

        Args:
            boxes: Resultados de detecção YOLO (boxes).
            frame_height: Altura do frame.
            frame_width: Largura do frame.

        Returns:
            Tuple (bbox, class_name, confidence, score) ou None.
        """
        frame_area = frame_height * frame_width
        best_score = -1
        best_result = None

        for i in range(len(boxes)):
            bbox = boxes.xyxy[i].cpu().numpy()
            confidence = float(boxes.conf[i])
            x1, y1, x2, y2 = bbox

            # Filtra detecções menores que área mínima
            det_area = (x2 - x1) * (y2 - y1)
            area_ratio = det_area / frame_area
            if area_ratio < BED_MIN_AREA_RATIO:
                continue

            score = self._calculate_bed_score(
                bbox, frame_height, frame_width, confidence
            )

            if score > best_score:
                best_score = score
                class_id = int(boxes.cls[i])
                class_name = self.model.names[class_id]
                best_result = (
                    tuple(bbox.astype(int)),
                    class_name,
                    confidence,
                    score,
                )

        return best_result

    def _log_detections(
        self,
        strategy_name: str,
        boxes,
        frame_height: int,
        frame_width: int,
    ) -> None:
        """
        Loga detalhes de cada detecção para diagnóstico.

        Args:
            strategy_name: Nome da estratégia usada.
            boxes: Resultados de detecção YOLO (boxes).
            frame_height: Altura do frame.
            frame_width: Largura do frame.
        """
        frame_area = frame_height * frame_width

        if len(boxes) == 0:
            print(f"    [{strategy_name}] Nenhuma deteccao")
            return

        for i in range(len(boxes)):
            bbox = boxes.xyxy[i].cpu().numpy()
            confidence = float(boxes.conf[i])
            class_id = int(boxes.cls[i])
            class_name = self.model.names[class_id]

            x1, y1, x2, y2 = bbox
            det_area = (x2 - x1) * (y2 - y1)
            area_pct = (det_area / frame_area) * 100

            score = self._calculate_bed_score(
                bbox, frame_height, frame_width, confidence
            )

            bbox_str = f"({int(x1)},{int(y1)},{int(x2)},{int(y2)})"
            print(f"    [{strategy_name}] {class_name}: conf={confidence:.3f} "
                  f"bbox={bbox_str} area={area_pct:.1f}% score={score:.3f}")

    def detect_bed(
        self,
        frame: np.ndarray,
        diagnostic: bool = False,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Executa detecção multi-estratégia buscando cama no frame.

        Itera pelas estratégias em ordem de prioridade. Para cada uma,
        executa inferência com as classes e threshold correspondentes.
        Na estratégia exploratória, apenas loga (não retorna detecção).

        Args:
            frame: Frame de vídeo (numpy array BGR).
            diagnostic: Se True, força log detalhado de todas as detecções.

        Returns:
            Tuple (x1, y1, x2, y2) com coordenadas da cama ou None se não detectada.
        """
        if not self.strategies:
            return None

        frame_height, frame_width = frame.shape[:2]
        do_log = diagnostic or BED_DETECTION_DIAGNOSTIC

        for strategy in self.strategies:
            results = self.model.predict(
                frame,
                classes=strategy["class_indices"],
                conf=strategy["conf"],
                verbose=False,
            )

            has_detections = (
                len(results) > 0 and len(results[0].boxes) > 0
            )

            if do_log and has_detections:
                self._log_detections(
                    strategy["name"],
                    results[0].boxes,
                    frame_height,
                    frame_width,
                )
            elif do_log and not has_detections:
                print(f"    [{strategy['name']}] Nenhuma deteccao")

            if has_detections and strategy["returns_detection"]:
                best = self._select_best_detection(
                    results[0].boxes, frame_height, frame_width
                )
                if best is not None:
                    bbox, class_name, confidence, score = best
                    self.detected_class_name = class_name
                    self.detected_strategy = strategy["name"]
                    self.bed_bbox = bbox
                    self.last_detection_time = time.time()

                    if do_log:
                        print(f"    >>> Selecionada: {class_name} via estrategia "
                              f"'{strategy['name']}' (conf={confidence:.3f}, score={score:.3f})")

                    return self.bed_bbox

        return None

    def save_reference(self, bbox: Tuple[int, int, int, int]) -> None:
        """
        Persiste coordenadas da cama em arquivo JSON com metadados.

        Args:
            bbox: Tuple (x1, y1, x2, y2) com coordenadas.
        """
        self.reference_path.parent.mkdir(parents=True, exist_ok=True)

        # Converte numpy int64 para int nativo Python
        data = {
            "bbox": [int(v) for v in bbox],
            "timestamp": time.time(),
            "detected_class": self.detected_class_name,
            "detected_strategy": self.detected_strategy,
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
            # Carrega metadados se disponíveis (backward-compatible)
            self.detected_class_name = data.get("detected_class")
            self.detected_strategy = data.get("detected_strategy")
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
