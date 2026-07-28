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

import cv2
import numpy as np

from config import (
    ASETO_BED_CLASS_NAMES,
    ASETO_DETECTION_CONF,
    ASETO_MAX_AREA_RATIO,
    ASETO_VALIDATION_ENABLED,
    ASETO_VALIDATION_MIN_IOU,
    YOLO_ASETO_MODEL,
    BED_CLASS_NAMES,
    BED_CLASS_NAMES_PRIMARY,
    BED_CLASS_NAMES_SECONDARY,
    BED_DETECTION_CONF_COCO,
    BED_DETECTION_CONF_FALLBACK,
    BED_DETECTION_CONF_PRIMARY,
    BED_DETECTION_CONF_SECONDARY,
    BED_DETECTION_DIAGNOSTIC,
    BED_DETECTION_SENSITIVITY,
    BED_MAX_AREA_RATIO,
    BED_MIN_AREA_RATIO,
    BED_RECHECK_INTERVAL_HOURS,
    BED_REFERENCE_PATH,
)


def preprocess_ir_for_aseto(frame: np.ndarray) -> np.ndarray:
    """Converte frame IR para grayscale com CLAHE agressivo, retornando BGR."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def preprocess_ir_histeq(frame: np.ndarray) -> np.ndarray:
    """Aplica histogram equalization no frame IR, retornando BGR."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.equalizeHist(gray), cv2.COLOR_GRAY2BGR)


class BedDetector:
    """Detector de cama hospitalar usando YOLOv8 com múltiplas estratégias."""

    def __init__(self, yolo_model=None, aseto_model=None):
        """
        Inicializa o detector de cama.

        Args:
            yolo_model: Modelo YOLO COCO para inferência, ou None para carregar
                sob demanda via ensure_model_loaded() (economia de RAM no RPi).
            aseto_model: Modelo ASETO fine-tuned para cama hospitalar (opcional).
        """
        self.model = yolo_model
        self.aseto_model = aseto_model
        self.bed_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_detection_time: Optional[float] = None
        self.reference_path = Path(BED_REFERENCE_PATH)
        self.detected_class_name: Optional[str] = None
        self.detected_strategy: Optional[str] = None
        self.detected_confidence: float = 0.0
        self.detected_score: float = 0.0

        # Resolve nomes de classes para índices (legado, para recheck)
        self.bed_class_indices = self._resolve_class_names(BED_CLASS_NAMES) if yolo_model else []

        # Constrói estratégias de detecção (adiado se modelo for lazy)
        self.strategies = self._build_strategies() if yolo_model else []

        # Tenta carregar referência salva
        self.load_reference()

    def ensure_model_loaded(self, model_path: str) -> None:
        """
        Carrega o modelo de cama sob demanda.

        O modelo COCO (yolov8l) so e necessario durante calibracao/recheck —
        eventos raros. Mante-lo residente junto do modelo de pose estoura o
        orcamento de memoria do servico no Raspberry Pi (OOM-kill).
        """
        if self.model is not None:
            return
        from ultralytics import YOLO
        print(f"[BedDetector] Carregando modelo de cama {model_path} (sob demanda)...")
        self.model = YOLO(model_path)
        self.bed_class_indices = self._resolve_class_names(BED_CLASS_NAMES)
        self.strategies = self._build_strategies()

        # ASETO (fine-tuned p/ cama hospitalar) como VALIDADOR cruzado da
        # calibracao — o bbox dele e impreciso, mas ele sabe o que e uma cama
        # hospitalar; o COCO da o bbox, o ASETO confirma o objeto
        if ASETO_VALIDATION_ENABLED and self.aseto_model is None:
            aseto_path = Path(YOLO_ASETO_MODEL)
            if aseto_path.exists():
                try:
                    self.aseto_model = YOLO(str(aseto_path))
                    print(f"[BedDetector] Modelo ASETO carregado (validacao cruzada)")
                except Exception as e:
                    print(f"[BedDetector] Falha ao carregar ASETO ({e}) - validacao desativada")
            else:
                print(f"[BedDetector] ASETO nao encontrado em {YOLO_ASETO_MODEL} - validacao desativada")

    def release_model(self) -> None:
        """Libera os modelos de cama da memoria apos calibracao/recheck."""
        if self.model is None and self.aseto_model is None:
            return
        import gc
        self.model = None
        self.aseto_model = None
        self.strategies = []
        self.bed_class_indices = []
        gc.collect()
        print("[BedDetector] Modelos de cama liberados da memoria")

    def _resolve_class_names(self, class_names: list) -> list:
        """Resolve nomes de classes para índices usando model.names (COCO)."""
        return self._resolve_class_names_for_model(self.model, class_names)

    @staticmethod
    def _resolve_class_names_for_model(model, class_names: list) -> list:
        """
        Resolve nomes de classes para índices de um modelo específico.

        Args:
            model: Modelo YOLO com atributo .names.
            class_names: Lista de nomes de classes a resolver.

        Returns:
            Lista de índices correspondentes aos nomes fornecidos.
        """
        indices = []
        target_names = [n.lower() for n in class_names]

        for idx, name in model.names.items():
            if name.lower() in target_names:
                indices.append(idx)

        return indices

    @staticmethod
    def _apply_sensitivity(base_conf: float) -> float:
        sensitivity = max(1, min(10, BED_DETECTION_SENSITIVITY))
        # Level 1 (rigoroso)=4x base, Level 10 (sensivel)=0.3x base
        # COCO 0.10: range 0.40 (nivel 1) -> 0.03 (nivel 10)
        multiplier = 4.0 - (sensitivity - 1) * 3.7 / 9.0
        return max(0.01, min(0.50, base_conf * multiplier))

    def _build_strategies(self) -> List[Dict]:
        """
        Constrói lista ordenada de estratégias de detecção.

        Cada estratégia tem: nome, índices de classe, threshold de confiança,
        e flag indicando se retorna detecção ou apenas loga.

        Returns:
            Lista de dicts com estratégias ordenadas por prioridade.
        """
        strategies = []

        # Estratégia 0: COCO histEq no frame cru (melhor bbox para IR)
        # HistEq elimina color cast IR e COCO dá bbox preciso (~40% frame)
        histeq_indices = self._resolve_class_names(BED_CLASS_NAMES_SECONDARY)
        if histeq_indices:
            strategies.append({
                "name": "coco_histEq",
                "class_names": BED_CLASS_NAMES_SECONDARY,
                "class_indices": histeq_indices,
                "conf": self._apply_sensitivity(BED_DETECTION_CONF_COCO),
                "returns_detection": True,
                "preprocess": "histeq",
                "max_area_ratio": BED_MAX_AREA_RATIO,
            })

        # Estratégia 1: COCO no frame cru (fallback IR)
        raw_indices = self._resolve_class_names(BED_CLASS_NAMES_SECONDARY)
        if raw_indices:
            strategies.append({
                "name": "coco_raw",
                "class_names": BED_CLASS_NAMES_SECONDARY,
                "class_indices": raw_indices,
                "conf": self._apply_sensitivity(BED_DETECTION_CONF_COCO),
                "returns_detection": True,
                "preprocess": "raw",
                "max_area_ratio": BED_MAX_AREA_RATIO,
            })

        # Estratégia 2: Primary no frame normalizado (bed, couch)
        primary_indices = self._resolve_class_names(BED_CLASS_NAMES_PRIMARY)
        if primary_indices:
            strategies.append({
                "name": "primary",
                "class_names": BED_CLASS_NAMES_PRIMARY,
                "class_indices": primary_indices,
                "conf": self._apply_sensitivity(BED_DETECTION_CONF_PRIMARY),
                "returns_detection": True,
            })

        # Estratégia 3: Secondary (bed, couch, bench)
        secondary_indices = self._resolve_class_names(BED_CLASS_NAMES_SECONDARY)
        if secondary_indices:
            strategies.append({
                "name": "secondary",
                "class_names": BED_CLASS_NAMES_SECONDARY,
                "class_indices": secondary_indices,
                "conf": self._apply_sensitivity(BED_DETECTION_CONF_SECONDARY),
                "returns_detection": True,
            })

        # Estratégia 4: Exploratory (conf baixa)
        exploratory_indices = self._resolve_class_names(BED_CLASS_NAMES_SECONDARY)
        if exploratory_indices:
            strategies.append({
                "name": "exploratory",
                "class_names": BED_CLASS_NAMES_SECONDARY,
                "class_indices": exploratory_indices,
                "conf": self._apply_sensitivity(BED_DETECTION_CONF_FALLBACK),
                "returns_detection": True,
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
        model=None,
        max_area_ratio: float = BED_MAX_AREA_RATIO,
    ) -> Optional[Tuple[Tuple[int, int, int, int], str, float, float]]:
        """Filtra por área mínima e seleciona a melhor detecção."""
        model = model or self.model
        frame_area = frame_height * frame_width
        best_score = -1
        best_result = None

        for i in range(len(boxes)):
            bbox = boxes.xyxy[i].cpu().numpy()
            confidence = float(boxes.conf[i])
            x1, y1, x2, y2 = bbox

            det_area = (x2 - x1) * (y2 - y1)
            area_ratio = det_area / frame_area
            if area_ratio < BED_MIN_AREA_RATIO:
                continue
            if area_ratio > max_area_ratio:
                continue

            score = self._calculate_bed_score(
                bbox, frame_height, frame_width, confidence
            )

            if score > best_score:
                best_score = score
                class_id = int(boxes.cls[i])
                class_name = model.names[class_id]
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
        model=None,
    ) -> None:
        """Loga detalhes de cada detecção para diagnóstico."""
        model = model or self.model
        frame_area = frame_height * frame_width

        if len(boxes) == 0:
            print(f"    [{strategy_name}] Nenhuma deteccao")
            return

        for i in range(len(boxes)):
            bbox = boxes.xyxy[i].cpu().numpy()
            confidence = float(boxes.conf[i])
            class_id = int(boxes.cls[i])
            class_name = model.names[class_id]

            x1, y1, x2, y2 = bbox
            det_area = (x2 - x1) * (y2 - y1)
            area_pct = (det_area / frame_area) * 100

            score = self._calculate_bed_score(
                bbox, frame_height, frame_width, confidence
            )

            bbox_str = f"({int(x1)},{int(y1)},{int(x2)},{int(y2)})"
            print(f"    [{strategy_name}] {class_name}: conf={confidence:.3f} "
                  f"bbox={bbox_str} area={area_pct:.1f}% score={score:.3f}")

    @staticmethod
    def _bbox_iou(a: Tuple[float, float, float, float],
                  b: Tuple[float, float, float, float]) -> float:
        """IoU entre dois bboxes (x1, y1, x2, y2)."""
        ix1 = max(a[0], b[0])
        iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2])
        iy2 = min(a[3], b[3])
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if inter <= 0:
            return 0.0
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def _get_aseto_boxes(self, raw_frame: Optional[np.ndarray]) -> Optional[List[Tuple]]:
        """
        Roda o ASETO no frame cru e no pre-processado agressivo.

        Returns:
            Lista de bboxes detectados (pode ser vazia), ou None se a
            validacao estiver indisponivel (sem modelo/frame/erro).
        """
        if self.aseto_model is None or raw_frame is None:
            return None
        boxes = []
        try:
            for input_frame in (raw_frame, preprocess_ir_for_aseto(raw_frame)):
                results = self.aseto_model.predict(
                    input_frame, conf=ASETO_DETECTION_CONF, verbose=False
                )
                if len(results) > 0 and results[0].boxes is not None:
                    for i in range(len(results[0].boxes)):
                        boxes.append(tuple(results[0].boxes.xyxy[i].cpu().numpy()))
        except Exception:
            return None
        return boxes

    def _candidate_validated_by_aseto(
        self,
        bbox: Tuple[int, int, int, int],
        aseto_boxes: Optional[List[Tuple]],
    ) -> bool:
        """
        Valida o bbox candidato do COCO contra as deteccoes do ASETO.

        Protege contra calibrar na poltrona/sofa: se o ASETO enxerga a cama
        hospitalar em outro lugar, o candidato sem sobreposicao e rejeitado.
        Fail-open: ASETO indisponivel ou cego -> aceita (a validacao nao pode
        impedir a calibracao).
        """
        if aseto_boxes is None:
            return True
        if not aseto_boxes:
            print("    [aseto] Nenhuma deteccao ASETO - validacao inconclusiva (aceitando)")
            return True
        best_iou = max(self._bbox_iou(bbox, ab) for ab in aseto_boxes)
        validated = best_iou >= ASETO_VALIDATION_MIN_IOU
        print(f"    [aseto] IoU maximo candidato vs ASETO: {best_iou:.2f} -> "
              f"{'validado' if validated else 'REJEITADO'}")
        return validated

    def detect_bed(
        self,
        frame: np.ndarray,
        raw_frame: np.ndarray = None,
        diagnostic: bool = False,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Executa detecção multi-estratégia buscando cama no frame.

        Args:
            frame: Frame normalizado (para COCO).
            raw_frame: Frame cru antes da normalização IR (para ASETO).
            diagnostic: Se True, força log detalhado de todas as detecções.

        Returns:
            Tuple (x1, y1, x2, y2) com coordenadas da cama ou None se não detectada.
        """
        result = self.detect_bed_detailed(frame, raw_frame, diagnostic)
        if result is None:
            return None
        bbox, class_name, confidence, score = result
        self._accept_detection(bbox, class_name, confidence, score)
        return bbox

    def detect_bed_detailed(
        self,
        frame: np.ndarray,
        raw_frame: np.ndarray = None,
        diagnostic: bool = False,
    ) -> Optional[Tuple[Tuple[int, int, int, int], str, float, float]]:
        """
        Detecta cama sem sobrescrever a referência interna.

        Args:
            frame: Frame normalizado (para estratégias COCO).
            raw_frame: Frame cru (para estratégia ASETO).
            diagnostic: Se True, força log detalhado.

        Returns:
            Tuple (bbox, class_name, confidence, score) ou None.
        """
        if not self.strategies:
            return None

        frame_height, frame_width = frame.shape[:2]
        do_log = diagnostic or BED_DETECTION_DIAGNOSTIC

        # Deteccoes ASETO calculadas sob demanda (no primeiro candidato) e
        # reaproveitadas entre estrategias
        aseto_boxes: Optional[List[Tuple]] = None
        aseto_checked = False

        for strategy in self.strategies:
            model = strategy.get("model", self.model)
            preprocess = strategy.get("preprocess")

            if preprocess == "histeq" and raw_frame is not None:
                input_frame = preprocess_ir_histeq(raw_frame)
            elif preprocess == "raw" and raw_frame is not None:
                input_frame = raw_frame
            elif preprocess == "clahe_agr" and raw_frame is not None:
                input_frame = preprocess_ir_for_aseto(raw_frame)
            else:
                input_frame = frame

            results = model.predict(
                input_frame,
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
                    model=model,
                )
            elif do_log and not has_detections:
                print(f"    [{strategy['name']}] Nenhuma deteccao")

            if has_detections and strategy["returns_detection"]:
                max_area = strategy.get("max_area_ratio", BED_MAX_AREA_RATIO)
                best = self._select_best_detection(
                    results[0].boxes, frame_height, frame_width,
                    model=model, max_area_ratio=max_area,
                )
                if best is not None:
                    bbox, class_name, confidence, score = best

                    # Validacao cruzada: o COCO da o bbox, o ASETO confirma
                    # que o objeto e mesmo a cama hospitalar
                    if ASETO_VALIDATION_ENABLED:
                        if not aseto_checked:
                            aseto_boxes = self._get_aseto_boxes(raw_frame)
                            aseto_checked = True
                        if not self._candidate_validated_by_aseto(bbox, aseto_boxes):
                            if do_log:
                                print(f"    [{strategy['name']}] Candidato {class_name} "
                                      f"rejeitado pela validacao ASETO - tentando proxima estrategia")
                            continue

                    if do_log:
                        print(f"    >>> Selecionada: {class_name} via estrategia "
                              f"'{strategy['name']}' (conf={confidence:.3f}, score={score:.3f})")

                    return bbox, class_name, confidence, score

        return None

    def _accept_detection(
        self,
        bbox: Tuple[int, int, int, int],
        class_name: str,
        confidence: float,
        score: float,
    ) -> None:
        """Aceita uma detecção como referência atual."""
        self.bed_bbox = bbox
        self.detected_class_name = class_name
        self.detected_strategy = None
        self.detected_confidence = confidence
        self.detected_score = score
        self.last_detection_time = time.time()

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
            "confidence": float(self.detected_confidence),
            "score": float(self.detected_score),
        }

        from modules.atomic_io import atomic_write_json
        atomic_write_json(self.reference_path, data)

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
            self.detected_class_name = data.get("detected_class")
            self.detected_strategy = data.get("detected_strategy")
            self.detected_confidence = data.get("confidence", 0.0)
            self.detected_score = data.get("score", 0.0)
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
