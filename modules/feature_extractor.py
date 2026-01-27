"""
Módulo de extração de features para análise de movimento do paciente.
Calcula features temporais normalizadas para análise de estado.
"""

from collections import deque
from typing import Dict, Optional, Tuple

import numpy as np


class FeatureExtractor:
    """Extrai features normalizadas do paciente em relação à cama."""

    def __init__(self, bed_bbox: Tuple[int, int, int, int]):
        """
        Inicializa o extrator com referência da cama.

        Args:
            bed_bbox: Tuple (x1, y1, x2, y2) com coordenadas da cama.
        """
        self.bed_bbox = bed_bbox
        self.bed_x1, self.bed_y1, self.bed_x2, self.bed_y2 = bed_bbox
        self.bed_width = self.bed_x2 - self.bed_x1
        self.bed_height = self.bed_y2 - self.bed_y1
        self.bed_center_x = (self.bed_x1 + self.bed_x2) / 2
        self.bed_center_y = (self.bed_y1 + self.bed_y2) / 2

    def update_bed_bbox(self, bed_bbox: Tuple[int, int, int, int]) -> None:
        """
        Atualiza a referência da cama.

        Args:
            bed_bbox: Nova bbox da cama.
        """
        self.__init__(bed_bbox)

    def compute_rel_height(self, patient_bbox: Tuple[int, int, int, int]) -> float:
        """
        Calcula altura relativa do paciente em relação à cama.

        Args:
            patient_bbox: Tuple (x1, y1, x2, y2) do paciente.

        Returns:
            Razão altura_paciente / altura_cama.
        """
        _, y1, _, y2 = patient_bbox
        patient_height = y2 - y1

        if self.bed_height == 0:
            return 0.0

        return patient_height / self.bed_height

    def compute_y_top_norm(self, patient_bbox: Tuple[int, int, int, int]) -> float:
        """
        Calcula distância normalizada do topo do paciente ao topo da cama.

        Args:
            patient_bbox: Tuple (x1, y1, x2, y2) do paciente.

        Returns:
            Distância normalizada (pode ser negativa se acima da cama).
        """
        _, patient_y, _, _ = patient_bbox

        if self.bed_height == 0:
            return 0.0

        return (patient_y - self.bed_y1) / self.bed_height

    def compute_aspect_ratio(self, patient_bbox: Tuple[int, int, int, int]) -> float:
        """
        Calcula razão de aspecto do bbox do paciente.

        Args:
            patient_bbox: Tuple (x1, y1, x2, y2) do paciente.

        Returns:
            Razão largura / altura do paciente.
        """
        x1, y1, x2, y2 = patient_bbox
        width = x2 - x1
        height = y2 - y1

        if height == 0:
            return 0.0

        return width / height

    def compute_delta_y_top(self, buffer: deque) -> float:
        """
        Calcula velocidade vertical média baseada no buffer.

        Args:
            buffer: Deque com histórico de dados do paciente.

        Returns:
            Média das diferenças de y_top entre frames consecutivos.
        """
        if len(buffer) < 2:
            return 0.0

        deltas = []
        buffer_list = list(buffer)

        for i in range(1, len(buffer_list)):
            prev_y = buffer_list[i - 1]["y_top"]
            curr_y = buffer_list[i]["y_top"]
            deltas.append(curr_y - prev_y)

        return np.mean(deltas) if deltas else 0.0

    def compute_displacement_vector(self, buffer: deque) -> Tuple[float, float]:
        """
        Calcula vetor de deslocamento do centro de massa.

        Args:
            buffer: Deque com histórico de dados do paciente.

        Returns:
            Tuple (dx, dy) com tendência de movimento.
        """
        if len(buffer) < 2:
            return (0.0, 0.0)

        buffer_list = list(buffer)
        first = buffer_list[0]
        last = buffer_list[-1]

        dx = last["center_x"] - first["center_x"]
        dy = last["center_y"] - first["center_y"]

        # Normaliza pelo tamanho da cama
        if self.bed_width > 0:
            dx = dx / self.bed_width
        if self.bed_height > 0:
            dy = dy / self.bed_height

        return (dx, dy)

    def is_patient_outside_bed(
        self, patient_bbox: Tuple[int, int, int, int], margin: float = 0.1
    ) -> bool:
        """
        Verifica se o paciente está fora da área da cama.

        Args:
            patient_bbox: Tuple (x1, y1, x2, y2) do paciente.
            margin: Margem de tolerância (fração da cama).

        Returns:
            True se paciente está significativamente fora da cama.
        """
        px1, py1, px2, py2 = patient_bbox
        patient_center_x = (px1 + px2) / 2
        patient_center_y = (py1 + py2) / 2

        margin_x = self.bed_width * margin
        margin_y = self.bed_height * margin

        # Verifica se centro do paciente está fora da cama + margem
        outside_x = (
            patient_center_x < self.bed_x1 - margin_x
            or patient_center_x > self.bed_x2 + margin_x
        )
        outside_y = patient_center_y > self.bed_y2 + margin_y  # Abaixo da cama

        return outside_x or outside_y

    def extract_all(
        self, patient_bbox: Tuple[int, int, int, int], buffer: deque
    ) -> Dict[str, float]:
        """
        Extrai todas as features do paciente.

        Args:
            patient_bbox: Tuple (x1, y1, x2, y2) do paciente.
            buffer: Deque com histórico de dados.

        Returns:
            Dict com todas as features calculadas.
        """
        disp_x, disp_y = self.compute_displacement_vector(buffer)

        return {
            "rel_height": self.compute_rel_height(patient_bbox),
            "y_top_norm": self.compute_y_top_norm(patient_bbox),
            "aspect_ratio": self.compute_aspect_ratio(patient_bbox),
            "delta_y_top": self.compute_delta_y_top(buffer),
            "disp_x": disp_x,
            "disp_y": disp_y,
            "outside_bed": self.is_patient_outside_bed(patient_bbox),
        }
