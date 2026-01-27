"""
Módulo de máquina de estados finitos (FSM) para classificação do paciente.
Define estados e transições baseadas em features extraídas.
"""

from enum import Enum
from typing import Dict, Optional, Tuple


class SystemState(Enum):
    """Estados do sistema de monitoramento."""

    CONFIGURANDO = "CONFIGURANDO"        # Calibrando cama
    CONFIG_CONCLUIDA = "CONFIG_CONCLUIDA"  # Exibindo sucesso
    MONITORAMENTO = "MONITORAMENTO"      # Operação normal


class PatientState(Enum):
    """Estados possiveis do paciente (sistema legado baseado em bbox)."""

    VAZIO = "VAZIO"  # Nenhuma pessoa detectada
    REPOUSO = "REPOUSO"  # Paciente deitado (estavel)
    ALERTA = "ALERTA"  # Paciente sentando ou movimentando
    CRITICO = "CRITICO"  # Possivel queda detectada


class PatientPoseState(Enum):
    """Estados do paciente baseados em pose (keypoints YOLOv8-Pose)."""

    AGUARDANDO = "AGUARDANDO"          # Aguardando paciente ser detectado
    MONITORANDO = "MONITORANDO"        # Paciente na cama, monitoramento ativo
    RISCO_POTENCIAL = "RISCO_POTENCIAL"  # Partes do corpo fora da cama
    PACIENTE_FORA = "PACIENTE_FORA"    # Paciente fora da cama (critico)


class StateMachine:
    """Maquina de estados para classificacao do paciente."""

    # Cores BGR para cada estado (para visualizacao)
    STATE_COLORS = {
        PatientState.VAZIO: (128, 128, 128),  # Cinza
        PatientState.REPOUSO: (0, 255, 0),  # Verde
        PatientState.ALERTA: (0, 255, 255),  # Amarelo (BGR)
        PatientState.CRITICO: (0, 0, 255),  # Vermelho
    }

    # Cores BGR para estados de pose
    POSE_STATE_COLORS = {
        PatientPoseState.AGUARDANDO: (255, 255, 0),      # Ciano - aguardando
        PatientPoseState.MONITORANDO: (0, 255, 0),       # Verde - normal
        PatientPoseState.RISCO_POTENCIAL: (0, 165, 255), # Laranja - atencao
        PatientPoseState.PACIENTE_FORA: (0, 0, 255),     # Vermelho - critico
    }

    # Thresholds para transições de estado
    THRESHOLD_REL_HEIGHT_SITTING = 0.6
    THRESHOLD_DELTA_Y_ALERT = 5.0
    THRESHOLD_ASPECT_RATIO_LYING = 1.5

    def __init__(self):
        """Inicializa a FSM no estado VAZIO."""
        self.state: PatientState = PatientState.VAZIO
        self.previous_state: PatientState = PatientState.VAZIO
        self.state_duration: int = 0  # Frames no estado atual

    def update(self, features: Optional[Dict[str, float]], persons_count: int) -> PatientState:
        """
        Atualiza estado baseado em features e contagem de pessoas.

        Args:
            features: Dict com features calculadas ou None.
            persons_count: Número de pessoas detectadas.

        Returns:
            Novo estado do paciente.
        """
        self.previous_state = self.state
        new_state = self._compute_next_state(features, persons_count)

        if new_state == self.state:
            self.state_duration += 1
        else:
            self.state = new_state
            self.state_duration = 1

        return self.state

    def _compute_next_state(
        self, features: Optional[Dict[str, float]], persons_count: int
    ) -> PatientState:
        """
        Computa próximo estado baseado nas regras de transição.

        Args:
            features: Dict com features ou None.
            persons_count: Número de pessoas detectadas.

        Returns:
            Próximo estado calculado.
        """
        # Sem pessoas = Cama vazia
        if persons_count == 0:
            return PatientState.VAZIO

        # Mais de uma pessoa = Acompanhado, sem risco
        if persons_count > 1:
            return PatientState.REPOUSO

        # Uma pessoa sem features = Estado anterior ou REPOUSO
        if features is None:
            return self.state if self.state != PatientState.VAZIO else PatientState.REPOUSO

        # Análise de features para uma pessoa
        rel_height = features.get("rel_height", 0)
        delta_y_top = features.get("delta_y_top", 0)
        aspect_ratio = features.get("aspect_ratio", 0)
        outside_bed = features.get("outside_bed", False)

        # CRÍTICO: Paciente fora da área da cama
        if outside_bed:
            return PatientState.CRITICO

        # ALERTA: Movimento vertical significativo (sentando)
        if rel_height > self.THRESHOLD_REL_HEIGHT_SITTING:
            if abs(delta_y_top) > self.THRESHOLD_DELTA_Y_ALERT:
                return PatientState.ALERTA
            # Altura alta mas sem movimento = já sentado, ainda alerta
            return PatientState.ALERTA

        # REPOUSO: Paciente deitado (aspect ratio alto = horizontal)
        if aspect_ratio > self.THRESHOLD_ASPECT_RATIO_LYING:
            return PatientState.REPOUSO

        # Default: REPOUSO se nenhuma condição de risco
        return PatientState.REPOUSO

    def get_state(self) -> PatientState:
        """
        Retorna estado atual.

        Returns:
            PatientState atual.
        """
        return self.state

    def get_state_name(self) -> str:
        """
        Retorna nome do estado atual.

        Returns:
            String com nome do estado.
        """
        return self.state.value

    def get_state_color(self) -> Tuple[int, int, int]:
        """
        Retorna cor BGR para visualização do estado atual.

        Returns:
            Tuple (B, G, R) com cor do estado.
        """
        return self.STATE_COLORS.get(self.state, (128, 128, 128))

    def get_previous_state(self) -> PatientState:
        """
        Retorna estado anterior.

        Returns:
            PatientState anterior.
        """
        return self.previous_state

    def is_state_changed(self) -> bool:
        """
        Verifica se houve mudança de estado.

        Returns:
            True se estado mudou no último update.
        """
        return self.state != self.previous_state

    def get_state_duration(self) -> int:
        """
        Retorna duração no estado atual (em frames).

        Returns:
            Número de frames no estado atual.
        """
        return self.state_duration

    def reset(self) -> None:
        """Reseta FSM para estado inicial."""
        self.state = PatientState.VAZIO
        self.previous_state = PatientState.VAZIO
        self.state_duration = 0

    @classmethod
    def get_pose_state_color(cls, state: PatientPoseState) -> Tuple[int, int, int]:
        """
        Retorna cor BGR para estado de pose.

        Args:
            state: Estado de pose do paciente.

        Returns:
            Tuple (B, G, R) com cor do estado.
        """
        return cls.POSE_STATE_COLORS.get(state, (128, 128, 128))
