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
    EMA_ALPHA,
    EMA_THRESHOLD_ENTER_OUT,
    EMA_THRESHOLD_ENTER_RISK,
    EMA_THRESHOLD_EXIT_OUT,
    EMA_THRESHOLD_EXIT_RISK,
    EMA_THRESHOLD_PATIENT_DETECTED,
    EMA_THRESHOLD_PATIENT_LOST,
    KP_LEFT_ANKLE,
    KP_LEFT_HIP,
    KP_LEFT_KNEE,
    KP_LEFT_SHOULDER,
    KP_RIGHT_ANKLE,
    KP_RIGHT_HIP,
    KP_RIGHT_KNEE,
    KP_RIGHT_SHOULDER,
    POSE_CONFIDENCE_HIGH,
    POSE_CONFIDENCE_MIN,
    POSE_FRAMES_PATIENT_DETECTED,
    POSE_FRAMES_TO_CONFIRM,
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
        margin: float = 0.1,
    ) -> bool:
        """
        Verifica se ponto esta dentro da area da cama.

        Args:
            point: Coordenadas (x, y) do ponto
            margin: Margem percentual para considerar dentro da cama

        Returns:
            True se ponto esta dentro da cama (com margem)
        """
        x1, y1, x2, y2 = self.bed_bbox
        bed_width = x2 - x1
        bed_height = y2 - y1

        # Aplica margem
        margin_x = bed_width * margin
        margin_y = bed_height * margin

        x1_expanded = x1 - margin_x
        x2_expanded = x2 + margin_x
        y1_expanded = y1 - margin_y
        y2_expanded = y2 + margin_y

        px, py = point
        return x1_expanded <= px <= x2_expanded and y1_expanded <= py <= y2_expanded

    def analyze_position(self, body_points: BodyPoints) -> PositionAnalysis:
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
    """

    # Estados possiveis
    AGUARDANDO = "AGUARDANDO"
    MONITORANDO = "MONITORANDO"
    RISCO_POTENCIAL = "RISCO_POTENCIAL"
    PACIENTE_FORA = "PACIENTE_FORA"

    def __init__(
        self,
        alpha: float = EMA_ALPHA,
        threshold_enter_risk: float = EMA_THRESHOLD_ENTER_RISK,
        threshold_exit_risk: float = EMA_THRESHOLD_EXIT_RISK,
        threshold_enter_out: float = EMA_THRESHOLD_ENTER_OUT,
        threshold_exit_out: float = EMA_THRESHOLD_EXIT_OUT,
        threshold_patient_detected: float = EMA_THRESHOLD_PATIENT_DETECTED,
        threshold_patient_lost: float = EMA_THRESHOLD_PATIENT_LOST,
    ):
        """
        Inicializa a maquina de estados EMA.

        Args:
            alpha: Fator de suavizacao EMA (0-1). Maior = mais rapido.
            threshold_enter_risk: Score para entrar em RISCO_POTENCIAL
            threshold_exit_risk: Score para sair de RISCO_POTENCIAL
            threshold_enter_out: Score para entrar em PACIENTE_FORA
            threshold_exit_out: Score para sair de PACIENTE_FORA
            threshold_patient_detected: Score para confirmar paciente na cama
            threshold_patient_lost: Score para considerar paciente perdido
        """
        self.alpha = alpha
        self.threshold_enter_risk = threshold_enter_risk
        self.threshold_exit_risk = threshold_exit_risk
        self.threshold_enter_out = threshold_enter_out
        self.threshold_exit_out = threshold_exit_out
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
        self._frames_to_lose_patient = 15  # Frames sem pessoa para considerar paciente perdido

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
        # Se mais de uma pessoa, nao monitorar (acompanhado)
        if person_count > 1:
            # Mantem scores mas nao altera estado - paciente acompanhado
            self._frames_without_person = 0  # Reset contador
            return self.current_state

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

        # Se nao ha analise ou nenhuma pessoa, decai todos os scores
        if analysis is None or body_points is None or person_count == 0:
            self._decay_all_scores()
            self._update_state_from_scores(person_count)
            return self.current_state

        # Paciente visivel = pontos essenciais detectados OU modo ocluso
        signal_patient_visible = 1.0 if (analysis.core_points_visible or analysis.occluded_mode) else 0.0

        # Paciente na cama = pontos essenciais visiveis E dentro da cama
        signal_patient_in_bed = 1.0 if (
            analysis.core_points_visible and
            analysis.neck_in_bed and
            analysis.hip_in_bed
        ) else 0.0

        # Pontos essenciais (pescoco e quadris) fora da cama
        core_points_outside = (
            analysis.core_points_visible and
            analysis.neck_in_bed == False and
            analysis.hip_in_bed == False
        )

        # Risco = alguns pontos fora, outros dentro (mas nao todos fora)
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

        # Seguro = todos os pontos dentro da cama
        signal_safe = 1.0 if (
            analysis.points_monitored > 0 and
            analysis.all_monitored_in_bed
        ) else 0.0

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

        # Atualiza estado baseado nos scores
        self._update_state_from_scores(person_count)

        return self.current_state

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

    def _update_state_from_scores(self, person_count: int = 1) -> None:
        """Atualiza estado baseado nos scores EMA."""

        # Estado AGUARDANDO - esperando paciente ser detectado na cama
        if self.current_state == self.AGUARDANDO:
            # Paciente confirmado na cama = inicia monitoramento
            if self.score_patient_in_bed >= self.threshold_patient_detected:
                self.current_state = self.MONITORANDO
                self.patient_confirmed = True
            return

        # =====================================================================
        # A partir daqui, paciente ja foi confirmado (estados de monitoramento)
        # So volta para AGUARDANDO se paciente REALMENTE desaparecer da cena
        # =====================================================================

        # Verifica se perdeu o paciente completamente
        # Criterio: nenhuma pessoa detectada por varios frames consecutivos
        patient_lost = self._frames_without_person >= self._frames_to_lose_patient

        # Estado PACIENTE_FORA
        if self.current_state == self.PACIENTE_FORA:
            # So volta para AGUARDANDO se paciente desaparecer completamente
            if patient_lost:
                self.current_state = self.AGUARDANDO
                self.patient_confirmed = False
                return

            # Sai de PACIENTE_FORA se score de "fora" cair E paciente voltar para cama
            if self.score_out < self.threshold_exit_out and self.score_safe > self.threshold_exit_risk:
                self.current_state = self.MONITORANDO
            # Ou se entrar em risco parcial
            elif self.score_out < self.threshold_exit_out and self.score_risk >= self.threshold_enter_risk:
                self.current_state = self.RISCO_POTENCIAL
            return

        # Estado RISCO_POTENCIAL
        if self.current_state == self.RISCO_POTENCIAL:
            # So volta para AGUARDANDO se paciente desaparecer completamente
            if patient_lost:
                self.current_state = self.AGUARDANDO
                self.patient_confirmed = False
                return

            # Escala para PACIENTE_FORA se todos pontos sairem
            if self.score_out >= self.threshold_enter_out:
                self.current_state = self.PACIENTE_FORA
            # Volta para MONITORANDO apenas se risco diminuir E seguro aumentar significativamente
            elif self.score_risk < self.threshold_exit_risk and self.score_safe > self.threshold_exit_risk:
                self.current_state = self.MONITORANDO
            return

        # Estado MONITORANDO
        if self.current_state == self.MONITORANDO:
            # Volta para AGUARDANDO se paciente desaparecer
            if patient_lost:
                self.current_state = self.AGUARDANDO
                self.patient_confirmed = False
                return

            # Entra em PACIENTE_FORA (prioridade maior - todos pontos fora)
            if self.score_out >= self.threshold_enter_out:
                self.current_state = self.PACIENTE_FORA
            # Entra em RISCO_POTENCIAL (alguns pontos fora)
            elif self.score_risk >= self.threshold_enter_risk:
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
        """Reseta maquina de estados e scores."""
        self.current_state = self.AGUARDANDO
        self.patient_confirmed = False
        self.score_patient_visible = 0.0
        self.score_patient_in_bed = 0.0
        self.score_risk = 0.0
        self.score_out = 0.0
        self.score_safe = 0.0
        self._frames_without_person = 0
