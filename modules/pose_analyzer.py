"""
Modulo de analise de pose do paciente usando keypoints YOLOv8-Pose.

Extrai pontos do corpo dos keypoints COCO format e analisa posicao
em relacao a area da cama para determinar risco de queda.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import (
    ALERT_PERSISTENT_SAFE_FRAMES,
    BED_MARGIN_BOTTOM,
    BED_MARGIN_LEFT,
    BED_MARGIN_RIGHT,
    BED_MARGIN_TOP,
    COMPANION_ANALYSIS_ENABLED,
    COMPANION_RISK_ENTER_BOOST,
    CONFIDENCE_EMA_ALPHA,
    EMA_ALPHA,
    FRAMES_TO_LOSE_PATIENT,
    OCCLUSION_EMPTY_TIMEOUT_FRAMES,
    STATE_PUBLISH_DWELL_FRAMES,
    EMA_THRESHOLD_ENTER_OUT,
    EMA_THRESHOLD_ENTER_RISK,
    EMA_THRESHOLD_EXIT_OUT,
    EMA_THRESHOLD_EXIT_RISK,
    EMA_THRESHOLD_EXIT_SAFE,
    EMA_THRESHOLD_PATIENT_DETECTED,
    EMA_THRESHOLD_PATIENT_LOST,
    GRACE_PERIOD_AFTER_ACOMPANHADO,
    MULTI_PERSON_MAJORITY_MIN,
    MULTI_PERSON_WINDOW_SIZE,
    KP_LEFT_ANKLE,
    KP_LEFT_HIP,
    KP_LEFT_KNEE,
    KP_LEFT_SHOULDER,
    KP_RIGHT_ANKLE,
    KP_RIGHT_HIP,
    KP_RIGHT_KNEE,
    KP_RIGHT_SHOULDER,
    LYING_MAX_ASPECT_RATIO,
    NECK_ABOVE_BED_SITTING_RATIO,
    PERSON_BED_CONTAINMENT_MIN,
    PERSON_BBOX_ASPECT_RATIO_UPRIGHT,
    PERSON_BED_OVERLAP_MAX_STANDING,
    POSE_CONFIDENCE_HIGH,
    POSE_CONFIDENCE_MIN,
    POSE_FRAMES_PATIENT_DETECTED,
    POSE_FRAMES_TO_CONFIRM,
    POSE_MAJORITY_MIN,
    POSE_WINDOW_SIZE,
    SITTING_ANGLE_THRESHOLD,
    SITTING_MIN_ASPECT_RATIO,
    TORSO_RATIO_MIN_FOR_LYING,
)


@dataclass
class BodyPoints:
    """Pontos do corpo extraidos dos keypoints."""

    # Pontos calculados (coordenadas x, y)
    neck: Optional[Tuple[float, float]] = None       # Ponto medio ombros
    hip_center: Optional[Tuple[float, float]] = None  # Ponto medio quadris
    left_knee: Optional[Tuple[float, float]] = None
    right_knee: Optional[Tuple[float, float]] = None
    left_ankle: Optional[Tuple[float, float]] = None
    right_ankle: Optional[Tuple[float, float]] = None

    # Confianca de cada ponto
    neck_conf: float = 0.0
    hip_conf: float = 0.0
    left_knee_conf: float = 0.0
    right_knee_conf: float = 0.0
    left_ankle_conf: float = 0.0
    right_ankle_conf: float = 0.0

    # Ombros individuais
    left_shoulder: Optional[Tuple[float, float]] = None
    right_shoulder: Optional[Tuple[float, float]] = None
    left_shoulder_conf: float = 0.0
    right_shoulder_conf: float = 0.0

    def has_core_points(self, min_conf: float) -> bool:
        """Verifica se pontos essenciais (pescoco e quadris) estao visiveis."""
        return self.neck_conf >= min_conf and self.hip_conf >= min_conf

    def is_occluded_mode(self, min_conf: float) -> bool:
        """Verifica se esta em modo ocluso (pescoco visivel, quadris nao)."""
        return self.neck_conf >= min_conf and self.hip_conf < min_conf

    def get_monitored_points(self, min_conf: float) -> List[Tuple[str, Tuple[float, float], float]]:
        """
        Retorna lista de pontos monitorados com confianca suficiente.

        Returns:
            Lista de tuplas (nome, coordenadas, confianca)
        """
        points = []

        if self.neck and self.neck_conf >= min_conf:
            points.append(("neck", self.neck, self.neck_conf))

        if self.hip_center and self.hip_conf >= min_conf:
            points.append(("hip_center", self.hip_center, self.hip_conf))

        if self.left_knee and self.left_knee_conf >= min_conf:
            points.append(("left_knee", self.left_knee, self.left_knee_conf))

        if self.right_knee and self.right_knee_conf >= min_conf:
            points.append(("right_knee", self.right_knee, self.right_knee_conf))

        if self.left_ankle and self.left_ankle_conf >= min_conf:
            points.append(("left_ankle", self.left_ankle, self.left_ankle_conf))

        if self.right_ankle and self.right_ankle_conf >= min_conf:
            points.append(("right_ankle", self.right_ankle, self.right_ankle_conf))

        if self.left_shoulder and self.left_shoulder_conf >= min_conf:
            points.append(("left_shoulder", self.left_shoulder, self.left_shoulder_conf))

        if self.right_shoulder and self.right_shoulder_conf >= min_conf:
            points.append(("right_shoulder", self.right_shoulder, self.right_shoulder_conf))

        return points


@dataclass
class PositionAnalysis:
    """Resultado da analise de posicao do paciente."""

    # Status de cada ponto (True = dentro, False = fora, None = nao detectado)
    neck_in_bed: Optional[bool] = None
    hip_in_bed: Optional[bool] = None
    left_knee_in_bed: Optional[bool] = None
    right_knee_in_bed: Optional[bool] = None
    left_ankle_in_bed: Optional[bool] = None
    right_ankle_in_bed: Optional[bool] = None
    left_shoulder_in_bed: Optional[bool] = None
    right_shoulder_in_bed: Optional[bool] = None

    # Resumo
    all_monitored_in_bed: bool = True
    any_outside_bed: bool = False
    all_outside_bed: bool = False
    core_points_visible: bool = False
    occluded_mode: bool = False

    # Detecção de postura (pessoa em pé vs deitada)
    is_standing: Optional[bool] = None            # True = pessoa provavelmente em pé
    person_bbox_aspect_ratio: Optional[float] = None  # height/width do bbox da pessoa
    person_bed_overlap: Optional[float] = None    # Fração do bbox da pessoa dentro da cama (0-1)
    torso_ratio: Optional[float] = None           # Dist pescoço-quadril / bbox_height

    # Detecção de postura sentada (risco de queda)
    is_sitting: Optional[bool] = None             # True = postura sentada detectada
    torso_hip_knee_angle: Optional[float] = None  # Ângulo pescoço-quadril-joelho em graus
    neck_above_bed_ratio: Optional[float] = None  # Quanto acima do topo da cama (fallback sitting)

    # Contenção pessoa/cama
    person_bed_containment: Optional[float] = None  # Fração do bbox contida na cama expandida (0-1)

    # Detecção explícita de deitado
    is_lying: Optional[bool] = None               # True = postura deitada detectada

    # Contagem
    points_inside: int = 0
    points_outside: int = 0
    points_monitored: int = 0


class PoseAnalyzer:
    """Analisa pose do paciente a partir de keypoints YOLOv8."""

    def __init__(
        self,
        bed_bbox: Tuple[int, int, int, int],
        confidence_high: float = POSE_CONFIDENCE_HIGH,
        confidence_min: float = POSE_CONFIDENCE_MIN,
        frames_to_confirm: int = POSE_FRAMES_TO_CONFIRM,
        frames_patient_detected: int = POSE_FRAMES_PATIENT_DETECTED,
    ):
        """
        Inicializa o analisador de pose.

        Args:
            bed_bbox: Bbox da cama (x1, y1, x2, y2)
            confidence_high: Threshold de confianca alta
            confidence_min: Threshold de confianca minima
            frames_to_confirm: Frames para confirmar mudanca de estado
            frames_patient_detected: Frames para confirmar paciente na cama
        """
        self.bed_bbox = bed_bbox
        self.confidence_high = confidence_high
        self.confidence_min = confidence_min
        self.frames_to_confirm = frames_to_confirm
        self.frames_patient_detected = frames_patient_detected

        # Buffers para persistencia de estados
        self.state_buffer: deque = deque(maxlen=frames_to_confirm)
        self.detection_buffer: deque = deque(maxlen=frames_patient_detected)

        # EMA para suavização de confiança de keypoints
        self._confidence_ema: Dict[int, float] = {}
        self._confidence_alpha = CONFIDENCE_EMA_ALPHA

    def smooth_confidences(self, confidences: np.ndarray) -> np.ndarray:
        """Aplica EMA às confianças de keypoints para evitar flickering."""
        smoothed = confidences.copy()
        for i in range(len(confidences)):
            if i in self._confidence_ema:
                smoothed[i] = (self._confidence_alpha * confidences[i] +
                               (1 - self._confidence_alpha) * self._confidence_ema[i])
            self._confidence_ema[i] = float(smoothed[i])
        return smoothed

    def reset_confidence_ema(self) -> None:
        """Reseta estado da suavização de confiança."""
        self._confidence_ema.clear()

    def update_bed_bbox(self, bed_bbox: Tuple[int, int, int, int]) -> None:
        """Atualiza bbox da cama."""
        self.bed_bbox = bed_bbox

    def extract_body_points(
        self,
        keypoints: np.ndarray,
        confidences: np.ndarray,
    ) -> BodyPoints:
        """
        Extrai pontos do corpo dos keypoints YOLO.

        Args:
            keypoints: Array de keypoints (17, 2) com coordenadas x, y
            confidences: Array de confiancas (17,)

        Returns:
            BodyPoints com pontos extraidos
        """
        body = BodyPoints()

        # Extrai ombros para calcular pescoco
        left_shoulder = keypoints[KP_LEFT_SHOULDER]
        right_shoulder = keypoints[KP_RIGHT_SHOULDER]
        left_shoulder_conf = confidences[KP_LEFT_SHOULDER]
        right_shoulder_conf = confidences[KP_RIGHT_SHOULDER]

        # Calcula ponto medio dos ombros (pescoco)
        if left_shoulder_conf >= self.confidence_min and right_shoulder_conf >= self.confidence_min:
            neck_x = (left_shoulder[0] + right_shoulder[0]) / 2
            neck_y = (left_shoulder[1] + right_shoulder[1]) / 2
            body.neck = (neck_x, neck_y)
            body.neck_conf = min(left_shoulder_conf, right_shoulder_conf)

        # Armazena ombros individuais
        if left_shoulder_conf >= self.confidence_min:
            body.left_shoulder = (float(left_shoulder[0]), float(left_shoulder[1]))
            body.left_shoulder_conf = float(left_shoulder_conf)

        if right_shoulder_conf >= self.confidence_min:
            body.right_shoulder = (float(right_shoulder[0]), float(right_shoulder[1]))
            body.right_shoulder_conf = float(right_shoulder_conf)

        # Extrai quadris para calcular ponto medio
        left_hip = keypoints[KP_LEFT_HIP]
        right_hip = keypoints[KP_RIGHT_HIP]
        left_hip_conf = confidences[KP_LEFT_HIP]
        right_hip_conf = confidences[KP_RIGHT_HIP]

        # Calcula ponto medio dos quadris
        if left_hip_conf >= self.confidence_min and right_hip_conf >= self.confidence_min:
            hip_x = (left_hip[0] + right_hip[0]) / 2
            hip_y = (left_hip[1] + right_hip[1]) / 2
            body.hip_center = (hip_x, hip_y)
            body.hip_conf = min(left_hip_conf, right_hip_conf)

        # Extrai joelhos (se confianca suficiente)
        left_knee = keypoints[KP_LEFT_KNEE]
        left_knee_conf = confidences[KP_LEFT_KNEE]
        if left_knee_conf >= self.confidence_min:
            body.left_knee = (left_knee[0], left_knee[1])
            body.left_knee_conf = left_knee_conf

        right_knee = keypoints[KP_RIGHT_KNEE]
        right_knee_conf = confidences[KP_RIGHT_KNEE]
        if right_knee_conf >= self.confidence_min:
            body.right_knee = (right_knee[0], right_knee[1])
            body.right_knee_conf = right_knee_conf

        # Extrai tornozelos (se confianca suficiente)
        left_ankle = keypoints[KP_LEFT_ANKLE]
        left_ankle_conf = confidences[KP_LEFT_ANKLE]
        if left_ankle_conf >= self.confidence_min:
            body.left_ankle = (left_ankle[0], left_ankle[1])
            body.left_ankle_conf = left_ankle_conf

        right_ankle = keypoints[KP_RIGHT_ANKLE]
        right_ankle_conf = confidences[KP_RIGHT_ANKLE]
        if right_ankle_conf >= self.confidence_min:
            body.right_ankle = (right_ankle[0], right_ankle[1])
            body.right_ankle_conf = right_ankle_conf

        return body

    def is_point_in_bed(
        self,
        point: Tuple[float, float],
    ) -> bool:
        """
        Verifica se ponto esta dentro da area da cama com margens assimetricas.

        Usa margens diferentes por lado para compensar a perspectiva da camera
        overhead (~45 graus). A margem do topo eh maior porque a cabeca do
        paciente sentado se projeta acima do bbox do colchao.

        Args:
            point: Coordenadas (x, y) do ponto

        Returns:
            True se ponto esta dentro da zona expandida da cama
        """
        x1, y1, x2, y2 = self.bed_bbox
        bed_width = x2 - x1
        bed_height = y2 - y1

        # Margens assimetricas (y1=topo da imagem, y2=base)
        x1_expanded = x1 - bed_width * BED_MARGIN_LEFT
        x2_expanded = x2 + bed_width * BED_MARGIN_RIGHT
        y1_expanded = y1 - bed_height * BED_MARGIN_TOP
        y2_expanded = y2 + bed_height * BED_MARGIN_BOTTOM

        px, py = point
        return x1_expanded <= px <= x2_expanded and y1_expanded <= py <= y2_expanded

    def analyze_position(
        self,
        body_points: BodyPoints,
        person_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> PositionAnalysis:
        """
        Analisa posicao do paciente em relacao a cama.

        Args:
            body_points: Pontos do corpo extraidos

        Returns:
            PositionAnalysis com resultado da analise
        """
        analysis = PositionAnalysis()

        # Verifica pontos essenciais
        analysis.core_points_visible = body_points.has_core_points(self.confidence_high)
        analysis.occluded_mode = body_points.is_occluded_mode(self.confidence_high)

        # Lista para contar pontos
        points_inside = 0
        points_outside = 0
        points_monitored = 0

        # Analisa pescoco
        if body_points.neck and body_points.neck_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.neck)
            analysis.neck_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        # Analisa ombros
        if body_points.left_shoulder and body_points.left_shoulder_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.left_shoulder)
            analysis.left_shoulder_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        if body_points.right_shoulder and body_points.right_shoulder_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.right_shoulder)
            analysis.right_shoulder_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        # Analisa quadris
        if body_points.hip_center and body_points.hip_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.hip_center)
            analysis.hip_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        # Analisa joelhos (apenas se confianca alta)
        if body_points.left_knee and body_points.left_knee_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.left_knee)
            analysis.left_knee_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        if body_points.right_knee and body_points.right_knee_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.right_knee)
            analysis.right_knee_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        # Analisa tornozelos (apenas se confianca alta)
        if body_points.left_ankle and body_points.left_ankle_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.left_ankle)
            analysis.left_ankle_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        if body_points.right_ankle and body_points.right_ankle_conf >= self.confidence_high:
            in_bed = self.is_point_in_bed(body_points.right_ankle)
            analysis.right_ankle_in_bed = in_bed
            points_monitored += 1
            if in_bed:
                points_inside += 1
            else:
                points_outside += 1

        # --- Detecção de pessoa em pé (passante) ---
        standing_signals = 0

        if person_bbox is not None:
            px1, py1, px2, py2 = person_bbox
            p_height = py2 - py1
            p_width = px2 - px1
            p_area = p_height * p_width

            # Critério 1: Bbox alto e estreito (aspect ratio)
            if p_width > 0:
                bbox_ar = p_height / p_width
                analysis.person_bbox_aspect_ratio = bbox_ar
                if bbox_ar > PERSON_BBOX_ASPECT_RATIO_UPRIGHT:
                    standing_signals += 1

            # Critério 2: Baixa sobreposição entre bbox da pessoa e bbox da cama
            bed_x1, bed_y1, bed_x2, bed_y2 = self.bed_bbox
            if p_area > 0:
                inter_x1 = max(px1, bed_x1)
                inter_y1 = max(py1, bed_y1)
                inter_x2 = min(px2, bed_x2)
                inter_y2 = min(py2, bed_y2)
                inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
                overlap = inter_area / p_area
                analysis.person_bed_overlap = overlap
                if overlap < PERSON_BED_OVERLAP_MAX_STANDING:
                    standing_signals += 1

            # Critério 3: Torso comprimido (foreshortening = deitado → desconta)
            if (body_points.neck and body_points.hip_center and
                    body_points.neck_conf >= self.confidence_high and
                    body_points.hip_conf >= self.confidence_high and
                    p_height > 0):
                neck_y = body_points.neck[1]
                hip_y = body_points.hip_center[1]
                torso_px = abs(neck_y - hip_y)
                torso_ratio = torso_px / p_height
                analysis.torso_ratio = torso_ratio
                if torso_ratio < TORSO_RATIO_MIN_FOR_LYING:
                    standing_signals -= 1

            analysis.is_standing = standing_signals >= 2

            # --- Detecção de postura sentada (ângulo pescoço-quadril-joelho) ---
            # Requer: não em pé, bbox não-horizontal (AR >= 0.7), pontos com alta confiança
            # AR < 0.7 indica pessoa deitada (bbox mais largo que alto) → pular
            if (not analysis.is_standing and
                    analysis.person_bbox_aspect_ratio is not None and
                    analysis.person_bbox_aspect_ratio >= SITTING_MIN_ASPECT_RATIO and
                    body_points.neck and body_points.hip_center and
                    body_points.neck_conf >= self.confidence_high and
                    body_points.hip_conf >= self.confidence_high):
                # Escolhe joelho com maior confiança (requer confiança alta)
                best_knee = None
                best_knee_conf = 0.0
                if body_points.left_knee and body_points.left_knee_conf >= self.confidence_high:
                    best_knee = body_points.left_knee
                    best_knee_conf = body_points.left_knee_conf
                if (body_points.right_knee and
                        body_points.right_knee_conf >= self.confidence_high and
                        body_points.right_knee_conf > best_knee_conf):
                    best_knee = body_points.right_knee

                if best_knee is not None:
                    # Vetores: hip→neck e hip→knee
                    vec_neck = (body_points.neck[0] - body_points.hip_center[0],
                                body_points.neck[1] - body_points.hip_center[1])
                    vec_knee = (best_knee[0] - body_points.hip_center[0],
                                best_knee[1] - body_points.hip_center[1])

                    # Magnitudes
                    mag_neck = np.sqrt(vec_neck[0]**2 + vec_neck[1]**2)
                    mag_knee = np.sqrt(vec_knee[0]**2 + vec_knee[1]**2)

                    if mag_neck > 0 and mag_knee > 0:
                        dot = vec_neck[0] * vec_knee[0] + vec_neck[1] * vec_knee[1]
                        cos_angle = np.clip(dot / (mag_neck * mag_knee), -1.0, 1.0)
                        angle_deg = float(np.degrees(np.arccos(cos_angle)))
                        analysis.torso_hip_knee_angle = angle_deg
                        analysis.is_sitting = angle_deg <= SITTING_ANGLE_THRESHOLD

            # --- Fallback: sentado por altura do pescoço (cobre quadril ocluso) ---
            if (analysis.is_sitting is None and
                    not (analysis.is_standing is True) and
                    body_points.neck and body_points.neck_conf >= self.confidence_high):
                bed_y1 = self.bed_bbox[1]
                bed_height = self.bed_bbox[3] - self.bed_bbox[1]
                neck_y = body_points.neck[1]
                if bed_height > 0:
                    above_ratio = (bed_y1 - neck_y) / bed_height  # Positivo = acima
                    analysis.neck_above_bed_ratio = above_ratio
                    if above_ratio > NECK_ABOVE_BED_SITTING_RATIO:
                        analysis.is_sitting = True

            # --- Detecção explícita de deitado ---
            if (not (analysis.is_standing is True) and
                    not (analysis.is_sitting is True) and
                    person_bbox is not None):
                if (analysis.person_bbox_aspect_ratio is not None and
                        analysis.person_bbox_aspect_ratio < LYING_MAX_ASPECT_RATIO):
                    analysis.is_lying = True
                elif (analysis.torso_ratio is not None and
                        analysis.torso_ratio < TORSO_RATIO_MIN_FOR_LYING):
                    analysis.is_lying = True

            # --- Contenção: fração do bbox da pessoa dentro da cama COM margens ---
            if p_area > 0:
                bed_x1, bed_y1, bed_x2, bed_y2 = self.bed_bbox
                bed_width = bed_x2 - bed_x1
                bed_height = bed_y2 - bed_y1
                exp_x1 = bed_x1 - bed_width * BED_MARGIN_LEFT
                exp_x2 = bed_x2 + bed_width * BED_MARGIN_RIGHT
                exp_y1 = bed_y1 - bed_height * BED_MARGIN_TOP
                exp_y2 = bed_y2 + bed_height * BED_MARGIN_BOTTOM
                ct_x1 = max(px1, exp_x1)
                ct_y1 = max(py1, exp_y1)
                ct_x2 = min(px2, exp_x2)
                ct_y2 = min(py2, exp_y2)
                ct_area = max(0, ct_x2 - ct_x1) * max(0, ct_y2 - ct_y1)
                analysis.person_bed_containment = ct_area / p_area

        # Calcula resumo
        analysis.points_inside = points_inside
        analysis.points_outside = points_outside
        analysis.points_monitored = points_monitored

        if points_monitored > 0:
            analysis.all_monitored_in_bed = (points_outside == 0)
            analysis.any_outside_bed = (points_outside > 0)
            analysis.all_outside_bed = (points_inside == 0)
        else:
            analysis.all_monitored_in_bed = False
            analysis.any_outside_bed = False
            analysis.all_outside_bed = False

        return analysis

    def add_state_to_buffer(self, state: str) -> None:
        """Adiciona estado ao buffer de persistencia."""
        self.state_buffer.append(state)

    def add_detection_to_buffer(self, detected: bool) -> None:
        """Adiciona deteccao ao buffer de deteccao de paciente."""
        self.detection_buffer.append(detected)

    def get_confirmed_state(self) -> Optional[str]:
        """
        Retorna estado confirmado se buffer esta cheio e consistente.

        Returns:
            Nome do estado se confirmado, None caso contrario
        """
        if len(self.state_buffer) < self.frames_to_confirm:
            return None

        # Verifica se todos os estados no buffer sao iguais
        states = list(self.state_buffer)
        if len(set(states)) == 1:
            return states[0]

        return None

    def is_patient_confirmed(self) -> bool:
        """
        Verifica se paciente foi confirmado na cama por N frames.

        Returns:
            True se paciente confirmado
        """
        if len(self.detection_buffer) < self.frames_patient_detected:
            return False

        # Verifica se todas as deteccoes no buffer sao True
        return all(self.detection_buffer)

    def reset_buffers(self) -> None:
        """Reseta buffers de persistencia."""
        self.state_buffer.clear()
        self.detection_buffer.clear()


class PoseStateMachine:
    """Maquina de estados para pose do paciente."""

    # Estados possiveis
    AGUARDANDO = "AGUARDANDO"
    MONITORANDO = "MONITORANDO"
    RISCO_POTENCIAL = "RISCO_POTENCIAL"
    PACIENTE_FORA = "PACIENTE_FORA"

    def __init__(self, frames_to_confirm: int = POSE_FRAMES_TO_CONFIRM):
        """
        Inicializa a maquina de estados de pose.

        Args:
            frames_to_confirm: Frames para confirmar mudanca de estado
        """
        self.current_state = self.AGUARDANDO
        self.frames_to_confirm = frames_to_confirm
        self.state_buffer: deque = deque(maxlen=frames_to_confirm)
        self.detection_buffer: deque = deque(maxlen=POSE_FRAMES_PATIENT_DETECTED)
        self.patient_confirmed = False

    def update(
        self,
        analysis: Optional[PositionAnalysis],
        body_points: Optional[BodyPoints],
    ) -> str:
        """
        Atualiza estado baseado na analise de posicao.

        Args:
            analysis: Resultado da analise de posicao
            body_points: Pontos do corpo detectados

        Returns:
            Estado atual
        """
        # Se nao ha analise, nao podemos atualizar
        if analysis is None or body_points is None:
            self.detection_buffer.append(False)
            if self.current_state != self.AGUARDANDO:
                self.state_buffer.append(self.AGUARDANDO)
                if self._is_state_confirmed(self.AGUARDANDO):
                    self.current_state = self.AGUARDANDO
                    self.patient_confirmed = False
            return self.current_state

        # Estado AGUARDANDO - esperando paciente ser detectado na cama
        if self.current_state == self.AGUARDANDO:
            # Precisa de pontos essenciais com alta confianca E dentro da cama
            if analysis.core_points_visible and analysis.neck_in_bed and analysis.hip_in_bed:
                self.detection_buffer.append(True)
                # Verifica se paciente foi confirmado por N frames
                if len(self.detection_buffer) >= POSE_FRAMES_PATIENT_DETECTED and all(self.detection_buffer):
                    self.current_state = self.MONITORANDO
                    self.patient_confirmed = True
                    self.state_buffer.clear()
            else:
                self.detection_buffer.append(False)

            return self.current_state

        # Estados de monitoramento
        new_state = self._determine_monitoring_state(analysis)
        self.state_buffer.append(new_state)

        if self._is_state_confirmed(new_state):
            self.current_state = new_state

        return self.current_state

    def _determine_monitoring_state(self, analysis: PositionAnalysis) -> str:
        """Determina estado baseado na analise de posicao."""
        # Se nao tem pontos monitorados com confianca, mantem estado
        if analysis.points_monitored == 0:
            return self.current_state

        # PACIENTE_FORA - Todos os pontos monitorados fora da cama
        if analysis.all_outside_bed:
            return self.PACIENTE_FORA

        # RISCO_POTENCIAL - Alguns pontos fora, outros dentro
        if analysis.any_outside_bed and not analysis.all_outside_bed:
            return self.RISCO_POTENCIAL

        # MONITORANDO - Todos os pontos dentro da cama
        if analysis.all_monitored_in_bed:
            return self.MONITORANDO

        return self.current_state

    def _is_state_confirmed(self, state: str) -> bool:
        """Verifica se estado foi confirmado por N frames."""
        if len(self.state_buffer) < self.frames_to_confirm:
            return False

        recent_states = list(self.state_buffer)[-self.frames_to_confirm:]
        return all(s == state for s in recent_states)

    def get_state(self) -> str:
        """Retorna estado atual."""
        return self.current_state

    def is_patient_confirmed(self) -> bool:
        """Retorna se paciente foi confirmado na cama."""
        return self.patient_confirmed

    def reset(self) -> None:
        """Reseta maquina de estados."""
        self.current_state = self.AGUARDANDO
        self.state_buffer.clear()
        self.detection_buffer.clear()
        self.patient_confirmed = False


class PoseStateMachineEMA:
    """
    Maquina de estados para pose do paciente usando EMA.

    Usa Media Movel Exponencial para suavizar transicoes de estado,
    reduzindo falsos positivos sem sacrificar tempo de resposta.

    Principio fail-safe: um estado de alerta NUNCA e cancelado por
    ausencia de evidencia (paciente sumiu, keypoints fracos, oclusao).
    Nesses casos o alerta e mantido e escalado para ALERTA_PERSISTENTE,
    saindo apenas com evidencia positiva de seguranca ou reset manual.
    """

    # Estados possiveis
    AGUARDANDO = "AGUARDANDO"
    MONITORANDO = "MONITORANDO"
    RISCO_POTENCIAL = "RISCO_POTENCIAL"
    PACIENTE_FORA = "PACIENTE_FORA"
    ACOMPANHADO = "ACOMPANHADO"
    ALERTA_PERSISTENTE = "ALERTA_PERSISTENTE"

    # Estados que representam alerta ativo (nao podem decair sem evidencia)
    ALERT_STATES = (RISCO_POTENCIAL, PACIENTE_FORA, ALERTA_PERSISTENTE)

    # Frames desde a ultima pose em pe/sentada para considerar o sumico
    # "fisicamente plausivel" (paciente saiu andando) vs oclusao/queda
    RECENT_UPRIGHT_FRAMES = 25

    def __init__(
        self,
        alpha: float = EMA_ALPHA,
        threshold_enter_risk: float = EMA_THRESHOLD_ENTER_RISK,
        threshold_exit_risk: float = EMA_THRESHOLD_EXIT_RISK,
        threshold_enter_out: float = EMA_THRESHOLD_ENTER_OUT,
        threshold_exit_out: float = EMA_THRESHOLD_EXIT_OUT,
        threshold_exit_safe: float = EMA_THRESHOLD_EXIT_SAFE,
        threshold_patient_detected: float = EMA_THRESHOLD_PATIENT_DETECTED,
        threshold_patient_lost: float = EMA_THRESHOLD_PATIENT_LOST,
    ):
        self.alpha = alpha
        self.threshold_enter_risk = threshold_enter_risk
        self.threshold_exit_risk = threshold_exit_risk
        self.threshold_enter_out = threshold_enter_out
        self.threshold_exit_out = threshold_exit_out
        self.threshold_exit_safe = threshold_exit_safe
        self.threshold_patient_detected = threshold_patient_detected
        self.threshold_patient_lost = threshold_patient_lost

        # Estado atual
        self.current_state = self.AGUARDANDO
        self.patient_confirmed = False

        # Scores EMA para cada condicao
        self.score_patient_in_bed = 0.0    # Paciente detectado na cama
        self.score_risk = 0.0              # Alguns pontos fora da cama
        self.score_out = 0.0               # Todos pontos fora da cama
        self.score_safe = 0.0              # Todos pontos dentro da cama
        self.score_patient_visible = 0.0   # Paciente visivel (independente de posicao)

        # Contador para rastrear frames sem deteccao de pessoa
        self._frames_without_person = 0
        self._frames_to_lose_patient = FRAMES_TO_LOSE_PATIENT

        # Sliding window para confirmação por maioria (evita reset por oscilação isolada)
        self._standing_window = deque(maxlen=POSE_WINDOW_SIZE)
        self._sitting_window = deque(maxlen=POSE_WINDOW_SIZE)

        # Período de graça após sair de ACOMPANHADO (apenas modo legado)
        self._grace_period_frames = GRACE_PERIOD_AFTER_ACOMPANHADO
        self._grace_counter = 0
        self._in_grace_period = False

        # Sliding window para ACOMPANHADO (evita falsos por deteccao duplicada)
        self._multi_person_window = deque(maxlen=MULTI_PERSON_WINDOW_SIZE)

        # Modo acompanhante: analise do paciente continua com 2+ pessoas
        self._companion_analysis = COMPANION_ANALYSIS_ENABLED
        self.companion_present = False

        # Fail-safe: rastreio da ultima evidencia posicional do paciente
        self._last_core_in_bed: Optional[bool] = None
        self._frames_since_upright = self.RECENT_UPRIGHT_FRAMES + 1
        self._frames_insufficient = 0

        # Oclusao presumida na cama (paciente sumiu deitado, ex: cobertor)
        self.occlusion_presumed = False
        self._occlusion_frames = 0

        # Saida de ALERTA_PERSISTENTE exige evidencia positiva consecutiva
        self._persistent_safe_counter = 0

        # Publicacao com dwell anti-flapping (log/UI); GPIO usa current_state
        self.published_state = self.AGUARDANDO
        self._pending_published: Optional[str] = None
        self._pending_published_count = 0


    def update(
        self,
        analysis: Optional[PositionAnalysis],
        body_points: Optional[BodyPoints],
        person_count: int = 1,
    ) -> str:
        """
        Atualiza estado baseado na analise de posicao usando EMA.

        Args:
            analysis: Resultado da analise de posicao
            body_points: Pontos do corpo detectados
            person_count: Numero de pessoas detectadas no ambiente

        Returns:
            Estado atual
        """
        self._multi_person_window.append(person_count > 1)

        if not self._companion_analysis:
            # ----- MODO LEGADO (rollback via COMPANION_ANALYSIS_ENABLED=False) -----
            # Multi-pessoa vira estado terminal ACOMPANHADO e cega a analise.
            if person_count > 1:
                self._frames_without_person = 0
                if self.patient_confirmed and self.current_state != self.ACOMPANHADO:
                    if self._majority_vote(self._multi_person_window, MULTI_PERSON_MAJORITY_MIN):
                        self.current_state = self.ACOMPANHADO
                elif not self.patient_confirmed:
                    self._decay_all_scores()
                return self._publish(self.current_state)

            if self.current_state == self.ACOMPANHADO:
                self._decay_all_scores()
                self.current_state = self.AGUARDANDO
                self.patient_confirmed = False
                self._in_grace_period = True
                self._grace_counter = self._grace_period_frames
                self._standing_window.clear()
                self._sitting_window.clear()
                return self._publish(self.current_state)
        else:
            # ----- MODO ACOMPANHANTE: flag informativa, analise continua -----
            # A pessoa-paciente e selecionada pelo chamador (associacao com a
            # cama em main.py); aqui apenas registramos a presenca de terceiros.
            companion_now = self._majority_vote(self._multi_person_window, MULTI_PERSON_MAJORITY_MIN)
            if companion_now != self.companion_present:
                self.companion_present = companion_now
                if not companion_now:
                    # Nao reter votos antigos apos a saida do acompanhante
                    self._multi_person_window.clear()

        # Rastreia frames sem pessoa detectada
        # Logica robusta para lidar com falsos positivos intermitentes do YOLO
        if person_count == 0:
            self._frames_without_person += 1
        elif analysis is not None and (analysis.core_points_visible or analysis.occluded_mode):
            # So reseta se tiver pessoa COM pontos corporais visiveis (pessoa real)
            self._frames_without_person = 0
        else:
            # Pessoa detectada mas sem pontos visiveis = possivel falso positivo
            # Decrementa gradualmente em vez de resetar
            self._frames_without_person = max(0, self._frames_without_person - 1)

        # Período de graça: suprime risco enquanto cena estabiliza após ACOMPANHADO
        if self._in_grace_period:
            self._grace_counter -= 1
            if self._grace_counter <= 0:
                self._in_grace_period = False

        # Frame sem evidencia do paciente (ninguem detectado ou sem keypoints)
        if analysis is None or body_points is None or person_count == 0:
            self._handle_no_evidence()
            return self._publish(self._display_state())

        # Paciente visivel = pontos essenciais detectados OU modo ocluso
        signal_patient_visible = 1.0 if (analysis.core_points_visible or analysis.occluded_mode) else 0.0

        # Paciente na cama = pontos essenciais visiveis E dentro da cama E NÃO em pé
        signal_patient_in_bed = 1.0 if (
            analysis.core_points_visible and
            analysis.neck_in_bed and
            analysis.hip_in_bed and
            not (analysis.is_standing is True)
        ) else 0.0

        # Pontos essenciais (pescoco e quadris) fora da cama
        core_points_outside = (
            analysis.core_points_visible and
            analysis.neck_in_bed == False and
            analysis.hip_in_bed == False
        )

        # Risco = alguns pontos fora (mas nao todos)
        # Nota: sitting eh adicionado DEPOIS da confirmacao multi-frame
        signal_risk = 1.0 if (
            analysis.points_monitored > 0 and
            analysis.any_outside_bed and
            not analysis.all_outside_bed and
            not core_points_outside  # Se pontos essenciais fora, nao eh risco, eh FORA
        ) else 0.0

        # Fora = todos os pontos monitorados fora da cama OU pontos essenciais fora
        signal_out = 1.0 if (
            (analysis.points_monitored > 0 and analysis.all_outside_bed) or
            core_points_outside
        ) else 0.0

        # Seguro = todos os pontos dentro da cama (sitting ajustado apos confirmacao)
        signal_safe = 1.0 if (
            analysis.points_monitored > 0 and
            analysis.all_monitored_in_bed
        ) else 0.0

        # Sliding window de persistencia de pose (maioria na janela, tolerante a oscilação)
        self._standing_window.append(analysis.is_standing is True)
        self._sitting_window.append(analysis.is_sitting is True)

        standing_confirmed = self._majority_vote(self._standing_window, POSE_MAJORITY_MIN)
        sitting_confirmed = self._majority_vote(self._sitting_window, POSE_MAJORITY_MIN)

        # Evidencia presente: limpa presuncao de oclusao na cama
        self.occlusion_presumed = False
        self._occlusion_frames = 0

        # Rastreia ultima posicao conhecida do nucleo do corpo (para decidir
        # entre oclusao presumida e sumico suspeito quando o paciente some)
        if analysis.core_points_visible:
            self._last_core_in_bed = bool(analysis.neck_in_bed and analysis.hip_in_bed)

        if standing_confirmed or sitting_confirmed:
            self._frames_since_upright = 0
        elif self._frames_since_upright <= self.RECENT_UPRIGHT_FRAMES:
            self._frames_since_upright += 1

        # Pessoa em pe confirmada: override de sinais
        if standing_confirmed:
            signal_patient_in_bed = 0.0
            signal_safe = 0.0
            if self.current_state == self.AGUARDANDO:
                # AGUARDANDO: passante — zera tudo para proteger contra falsos positivos
                signal_out = 0.0
                signal_risk = 0.0
            else:
                # Paciente confirmado se levantou: sinaliza risco de queda
                # Permite escalada MONITORANDO → RISCO → PACIENTE_FORA
                signal_risk = 1.0

        # Paciente sentado confirmado: risco mesmo com pontos na cama
        if sitting_confirmed and not standing_confirmed:
            signal_risk = 1.0
            signal_safe = 0.0

        # Pessoa com bbox muito fora da cama: comportamento similar a standing
        if (not standing_confirmed and
                analysis.person_bed_containment is not None and
                analysis.person_bed_containment < PERSON_BED_CONTAINMENT_MIN):
            signal_patient_in_bed = 0.0
            signal_safe = 0.0
            if self.current_state == self.AGUARDANDO:
                signal_out = 0.0
                signal_risk = 0.0

        # Override de sinais em modo ocluso (pescoco+ombros visiveis, quadris nao)
        if analysis.occluded_mode and not analysis.core_points_visible:
            # Coleta posicao dos pontos upper body
            upper_positions = []
            if analysis.neck_in_bed is not None:
                upper_positions.append(analysis.neck_in_bed)
            if analysis.left_shoulder_in_bed is not None:
                upper_positions.append(analysis.left_shoulder_in_bed)
            if analysis.right_shoulder_in_bed is not None:
                upper_positions.append(analysis.right_shoulder_in_bed)

            if upper_positions:
                all_in = all(upper_positions)
                all_out = not any(upper_positions)

                if all_in:
                    signal_patient_in_bed = 1.0
                    signal_safe = 1.0
                    signal_risk = 0.0
                    signal_out = 0.0
                elif all_out:
                    signal_out = 1.0
                    signal_patient_in_bed = 0.0
                    signal_safe = 0.0
                    signal_risk = 0.0
                else:
                    # Parcial - algum fora
                    signal_risk = 1.0
                    signal_patient_in_bed = 0.0
                    signal_safe = 0.0
                    signal_out = 0.0

        # Atualiza scores EMA
        self.score_patient_visible = self._ema(self.score_patient_visible, signal_patient_visible)
        self.score_patient_in_bed = self._ema(self.score_patient_in_bed, signal_patient_in_bed)
        self.score_risk = self._ema(self.score_risk, signal_risk)
        self.score_out = self._ema(self.score_out, signal_out)
        self.score_safe = self._ema(self.score_safe, signal_safe)

        # Evidencia positiva de seguranca no frame (usada para sair de
        # ALERTA_PERSISTENTE — exige paciente visivel E dentro da cama)
        safe_evidence = signal_safe >= 1.0 and signal_patient_in_bed >= 1.0

        # Atualiza estado baseado nos scores
        self._update_state_from_scores(person_count, safe_evidence)

        return self._publish(self._display_state())

    def _majority_vote(self, window: deque, min_count: int) -> bool:
        """Retorna True se pelo menos min_count elementos da janela sao True."""
        return sum(window) >= min_count

    def _ema(self, previous: float, current: float) -> float:
        """Calcula Media Movel Exponencial."""
        return self.alpha * current + (1 - self.alpha) * previous

    def _decay_all_scores(self) -> None:
        """Decai todos os scores quando nao ha deteccao."""
        self.score_patient_visible = self._ema(self.score_patient_visible, 0.0)
        self.score_patient_in_bed = self._ema(self.score_patient_in_bed, 0.0)
        self.score_risk = self._ema(self.score_risk, 0.0)
        self.score_out = self._ema(self.score_out, 0.0)
        self.score_safe = self._ema(self.score_safe, 0.0)

    def _handle_no_evidence(self) -> None:
        """
        Trata frame sem evidencia do paciente (ninguem detectado ou pessoa
        sem keypoints). Principio fail-safe: alerta ativo nunca decai aqui.
        """
        patient_lost = self._frames_without_person >= self._frames_to_lose_patient

        if self.current_state in self.ALERT_STATES:
            # FAIL-SAFE: ausencia de evidencia mantem o alerta (scores
            # congelados) e escala para ALERTA_PERSISTENTE — o cenario tipico
            # de queda real e o paciente sumir do enquadramento.
            self._persistent_safe_counter = 0
            if patient_lost and self.current_state != self.ALERTA_PERSISTENTE:
                self.current_state = self.ALERTA_PERSISTENTE
            return

        if self.current_state == self.MONITORANDO:
            if not patient_lost:
                self._decay_all_scores()
                return
            if self._last_core_in_bed is not False and \
                    self._frames_since_upright > self.RECENT_UPRIGHT_FRAMES:
                # Paciente sumiu deitado dentro da cama, sem ter sentado ou
                # levantado antes: presume oclusao (cobertor/equipamento).
                # Mantem MONITORANDO; so assume cama vazia apos timeout longo.
                self.occlusion_presumed = True
                self._occlusion_frames += 1
                if self._occlusion_frames >= OCCLUSION_EMPTY_TIMEOUT_FRAMES:
                    self._reset_to_aguardando()
                return
            # Sumico com ultima posicao parcialmente fora da cama ou logo apos
            # sentar/levantar: transicao fisicamente suspeita — fail-safe.
            self.current_state = self.RISCO_POTENCIAL
            return

        # AGUARDANDO (ou legado): decaimento normal
        self._decay_all_scores()
        self._update_state_from_scores(0)

    def _reset_to_aguardando(self) -> None:
        """Retorna ao estado inicial descartando o paciente confirmado."""
        self.current_state = self.AGUARDANDO
        self.patient_confirmed = False
        self.occlusion_presumed = False
        self._occlusion_frames = 0
        self._last_core_in_bed = None
        self._frames_insufficient = 0
        self._decay_all_scores()

    def _display_state(self) -> str:
        """Estado exibido: ACOMPANHADO substitui MONITORANDO quando ha visita."""
        if (self._companion_analysis and self.companion_present
                and self.current_state == self.MONITORANDO):
            return self.ACOMPANHADO
        return self.current_state

    def _publish(self, candidate: str) -> str:
        """
        Publica transicoes com dwell minimo (anti-flapping) para log/UI.
        Alertas criticos publicam imediatamente (fail-safe); o GPIO deve ler
        current_state diretamente, sem dwell.
        """
        if candidate == self.published_state:
            self._pending_published = None
            self._pending_published_count = 0
            return self.published_state

        if candidate in (self.PACIENTE_FORA, self.ALERTA_PERSISTENTE):
            self.published_state = candidate
            self._pending_published = None
            self._pending_published_count = 0
            return self.published_state

        if candidate != self._pending_published:
            self._pending_published = candidate
            self._pending_published_count = 1
        else:
            self._pending_published_count += 1

        if self._pending_published_count >= STATE_PUBLISH_DWELL_FRAMES:
            self.published_state = candidate
            self._pending_published = None
            self._pending_published_count = 0

        return self.published_state

    def _update_state_from_scores(self, person_count: int = 1, safe_evidence: bool = False) -> None:
        """Atualiza estado baseado nos scores EMA (com evidencia presente)."""

        # Estado AGUARDANDO - esperando paciente ser detectado na cama
        if self.current_state == self.AGUARDANDO:
            # Paciente confirmado na cama = inicia monitoramento
            if self.score_patient_in_bed >= self.threshold_patient_detected:
                self.current_state = self.MONITORANDO
                self.patient_confirmed = True
                self._in_grace_period = False
                self._frames_insufficient = 0
                self.score_risk = 0.0
                self.score_out = 0.0
            return

        # =====================================================================
        # A partir daqui, paciente ja foi confirmado (estados de monitoramento)
        # =====================================================================

        patient_lost = self._frames_without_person >= self._frames_to_lose_patient

        # Dados insuficientes: pessoa presente mas keypoints fracos/ruidosos.
        # Em estado de alerta isso NAO cancela o alerta (fail-safe): congela e,
        # se persistir, escala para ALERTA_PERSISTENTE.
        insufficient_data = (
            self.score_risk < 0.2 and
            self.score_out < 0.2 and
            self.score_safe < 0.2 and
            self.score_patient_visible < 0.3
        )

        # Estado ALERTA_PERSISTENTE: sai apenas com evidencia positiva
        # consecutiva de seguranca (paciente visivel e dentro da cama)
        if self.current_state == self.ALERTA_PERSISTENTE:
            if safe_evidence:
                self._persistent_safe_counter += 1
                if self._persistent_safe_counter >= ALERT_PERSISTENT_SAFE_FRAMES:
                    self.current_state = self.MONITORANDO
                    self.patient_confirmed = True
                    self._persistent_safe_counter = 0
                    self._frames_insufficient = 0
            else:
                self._persistent_safe_counter = 0
            return

        # Estado PACIENTE_FORA
        if self.current_state == self.PACIENTE_FORA:
            if patient_lost or insufficient_data:
                # FAIL-SAFE: sem evidencia nao ha des-escalada
                self._frames_insufficient += 1
                if self._frames_insufficient >= self._frames_to_lose_patient:
                    self.current_state = self.ALERTA_PERSISTENTE
                    self._frames_insufficient = 0
                return
            self._frames_insufficient = 0

            # Sai de PACIENTE_FORA se score de "fora" cair E paciente voltar para cama
            if self.score_out < self.threshold_exit_out and self.score_safe > self.threshold_exit_safe:
                self.current_state = self.MONITORANDO
            # Ou se entrar em risco parcial
            elif self.score_out < self.threshold_exit_out and self.score_risk >= self.threshold_enter_risk:
                self.current_state = self.RISCO_POTENCIAL
            # Escape da faixa morta: exige paciente visivel (senao congela)
            elif self.score_out < self.threshold_exit_out and self.score_patient_visible >= 0.3:
                self.current_state = self.RISCO_POTENCIAL
            return

        # Estado RISCO_POTENCIAL
        if self.current_state == self.RISCO_POTENCIAL:
            if patient_lost or insufficient_data:
                # FAIL-SAFE: sem evidencia nao ha des-escalada
                self._frames_insufficient += 1
                if self._frames_insufficient >= self._frames_to_lose_patient:
                    self.current_state = self.ALERTA_PERSISTENTE
                    self._frames_insufficient = 0
                return
            self._frames_insufficient = 0

            # Escala para PACIENTE_FORA se todos pontos sairem
            if self.score_out >= self.threshold_enter_out:
                self.current_state = self.PACIENTE_FORA
            # Volta para MONITORANDO apenas se risco diminuir E seguro subir o suficiente
            elif self.score_risk < self.threshold_exit_risk and self.score_safe > self.threshold_exit_safe:
                self.current_state = self.MONITORANDO
            return

        # Estado MONITORANDO
        if self.current_state == self.MONITORANDO:
            # patient_lost com analise presente = pessoa visivel sem pontos
            # confiaveis por muito tempo: evidencia fraca nao derruba paciente
            # confirmado (o caso sem pessoa alguma e tratado em _handle_no_evidence)
            if patient_lost:
                return

            # Suprime transições de risco durante período de graça (modo legado)
            if self._in_grace_period:
                return

            # Com acompanhante presente, threshold de risco levemente mais
            # conservador (compensa possiveis erros de associacao)
            enter_risk = self.threshold_enter_risk
            if self.companion_present:
                enter_risk = min(0.95, enter_risk + COMPANION_RISK_ENTER_BOOST)

            # Entra em RISCO_POTENCIAL (alguns pontos fora ou sentado)
            if self.score_risk >= enter_risk:
                self.current_state = self.RISCO_POTENCIAL
            # Entra em PACIENTE_FORA apenas se ja passou por RISCO_POTENCIAL
            # (evita salto direto MONITORANDO->PACIENTE_FORA em 2 frames)
            elif self.score_out >= self.threshold_enter_out:
                self.current_state = self.RISCO_POTENCIAL
            return

    def get_state(self) -> str:
        """Retorna estado atual."""
        return self.current_state

    def get_scores(self) -> dict:
        """Retorna scores EMA atuais para debug/visualizacao."""
        return {
            "visible": self.score_patient_visible,
            "in_bed": self.score_patient_in_bed,
            "risk": self.score_risk,
            "out": self.score_out,
            "safe": self.score_safe,
        }

    def is_patient_confirmed(self) -> bool:
        """Retorna se paciente foi confirmado na cama."""
        return self.patient_confirmed

    def reset(self) -> None:
        """Reseta maquina de estados e scores (inclusive ALERTA_PERSISTENTE)."""
        self.current_state = self.AGUARDANDO
        self.published_state = self.AGUARDANDO
        self.patient_confirmed = False
        self.companion_present = False
        self.occlusion_presumed = False
        self.score_patient_visible = 0.0
        self.score_patient_in_bed = 0.0
        self.score_risk = 0.0
        self.score_out = 0.0
        self.score_safe = 0.0
        self._frames_without_person = 0
        self._frames_insufficient = 0
        self._occlusion_frames = 0
        self._persistent_safe_counter = 0
        self._last_core_in_bed = None
        self._frames_since_upright = self.RECENT_UPRIGHT_FRAMES + 1
        self._pending_published = None
        self._pending_published_count = 0
        self._standing_window.clear()
        self._sitting_window.clear()
        self._multi_person_window.clear()
        self._grace_counter = 0
        self._in_grace_period = False
