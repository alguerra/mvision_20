"""
Módulo de monitoramento do paciente.
Gerencia buffer circular de dados e status do monitoramento.
"""

import time
from collections import deque
from typing import Dict, Optional, Tuple

from config import FEATURE_BUFFER_SIZE


class PatientMonitor:
    """Monitor de paciente com buffer circular para tracking temporal."""

    def __init__(self, bed_bbox: Tuple[int, int, int, int]):
        """
        Inicializa o monitor com referência da cama.

        Args:
            bed_bbox: Tuple (x1, y1, x2, y2) com coordenadas da cama.
        """
        self.bed_bbox = bed_bbox
        self.buffer: deque = deque(maxlen=FEATURE_BUFFER_SIZE)
        self.persons_count: int = 0
        self.status: str = "Cama Vazia"
        self.last_update: float = time.time()

    def update_bed_bbox(self, bed_bbox: Tuple[int, int, int, int]) -> None:
        """
        Atualiza a referência da cama.

        Args:
            bed_bbox: Nova bbox da cama.
        """
        self.bed_bbox = bed_bbox

    def update(self, persons_count: int) -> None:
        """
        Atualiza estado do monitor baseado na contagem de pessoas.

        Args:
            persons_count: Número de pessoas detectadas.
        """
        self.persons_count = persons_count
        self.last_update = time.time()

        if persons_count == 0:
            self.status = "Cama Vazia"
            self.buffer.clear()
        elif persons_count > 1:
            self.status = "Acompanhado"
        else:
            self.status = "Monitorando"

    def add_frame_data(self, patient_bbox: Tuple[int, int, int, int]) -> None:
        """
        Adiciona dados do frame atual ao buffer circular.

        Args:
            patient_bbox: Tuple (x1, y1, x2, y2) do paciente detectado.
        """
        x1, y1, x2, y2 = patient_bbox
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        frame_data = {
            "timestamp": time.time(),
            "bbox": patient_bbox,
            "y_top": y1,
            "center_x": center_x,
            "center_y": center_y,
            "width": x2 - x1,
            "height": y2 - y1,
        }

        self.buffer.append(frame_data)

    def get_status(self) -> str:
        """
        Retorna status atual do monitoramento.

        Returns:
            String com status: "Cama Vazia", "Acompanhado", ou "Monitorando".
        """
        return self.status

    def get_persons_count(self) -> int:
        """
        Retorna contagem atual de pessoas.

        Returns:
            Número de pessoas detectadas.
        """
        return self.persons_count

    def get_buffer_size(self) -> int:
        """
        Retorna tamanho atual do buffer.

        Returns:
            Número de frames no buffer.
        """
        return len(self.buffer)

    def get_latest_bbox(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Retorna a última bbox do paciente.

        Returns:
            Tuple com bbox ou None se buffer vazio.
        """
        if len(self.buffer) == 0:
            return None
        return self.buffer[-1]["bbox"]

    def get_tracking_duration(self) -> float:
        """
        Retorna duração do tracking atual em segundos.

        Returns:
            Tempo desde o primeiro frame no buffer.
        """
        if len(self.buffer) < 2:
            return 0.0

        first_timestamp = self.buffer[0]["timestamp"]
        last_timestamp = self.buffer[-1]["timestamp"]
        return last_timestamp - first_timestamp

    def is_buffer_full(self) -> bool:
        """
        Verifica se o buffer está cheio.

        Returns:
            True se buffer atingiu capacidade máxima.
        """
        return len(self.buffer) == self.buffer.maxlen

    def clear_buffer(self) -> None:
        """Limpa o buffer de dados."""
        self.buffer.clear()
