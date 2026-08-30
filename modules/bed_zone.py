"""
Zona da cama — definicao UNICA da geometria "dentro/fora da cama".

Antes desta unificacao coexistiam quatro definicoes de zona (FSM, overlap,
selecao de paciente e o desenho no monitor com margem fixa 0.1), e o que o
operador via colorido na tela nao era o que a FSM decidia. Todo consumidor
(pose_analyzer, gui/display, main) deve usar estas funcoes.

As margens sao relativas ao tamanho do bbox e assimetricas (ver config:
BED_MARGIN_*). Elas foram calibradas para camera overhead (~45 graus); a
revisao para camera frontal esta planejada como fase separada.
"""

from typing import Optional, Sequence, Tuple

from config import (
    BED_MARGIN_BOTTOM,
    BED_MARGIN_LEFT,
    BED_MARGIN_RIGHT,
    BED_MARGIN_TOP,
)

BBox = Tuple[float, float, float, float]


def expand_bed_bbox(
    bbox: Sequence[float],
    frame_size: Optional[Tuple[int, int]] = None,
) -> BBox:
    """
    Retorna a zona expandida da cama (x1, y1, x2, y2) com margens assimetricas.

    Args:
        bbox: Bbox cru da cama (x1, y1, x2, y2).
        frame_size: (largura, altura) opcional; se informado, a zona e
            recortada aos limites do frame (util para desenho).
    """
    x1, y1, x2, y2 = bbox
    bed_width = x2 - x1
    bed_height = y2 - y1

    ex1 = x1 - bed_width * BED_MARGIN_LEFT
    ex2 = x2 + bed_width * BED_MARGIN_RIGHT
    ey1 = y1 - bed_height * BED_MARGIN_TOP
    ey2 = y2 + bed_height * BED_MARGIN_BOTTOM

    if frame_size is not None:
        fw, fh = frame_size
        ex1 = max(0.0, ex1)
        ey1 = max(0.0, ey1)
        ex2 = min(float(fw - 1), ex2)
        ey2 = min(float(fh - 1), ey2)

    return (ex1, ey1, ex2, ey2)


def point_in_zone(point: Sequence[float], bbox: Sequence[float]) -> bool:
    """True se o ponto (x, y) esta dentro da zona expandida da cama."""
    ex1, ey1, ex2, ey2 = expand_bed_bbox(bbox)
    px, py = point
    return ex1 <= px <= ex2 and ey1 <= py <= ey2


def containment(person_bbox: Sequence[float], zone_bbox: Sequence[float]) -> float:
    """
    Fracao da area do bbox da pessoa contida em `zone_bbox` (0-1).

    `zone_bbox` pode ser a cama crua ou a expandida — quem chama decide.
    """
    px1, py1, px2, py2 = person_bbox
    p_area = max(0.0, px2 - px1) * max(0.0, py2 - py1)
    if p_area <= 0:
        return 0.0
    zx1, zy1, zx2, zy2 = zone_bbox
    ix1, iy1 = max(px1, zx1), max(py1, zy1)
    ix2, iy2 = min(px2, zx2), min(py2, zy2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    return inter / p_area


def bbox_touches_edges(
    bbox: Sequence[float],
    frame_size: Tuple[int, int],
    margin_px: int = 5,
) -> list:
    """
    Lista as bordas do frame tocadas pelo bbox ("left", "top", "right", "bottom").

    Cama encostada na borda = zona de queda fora do enquadramento (a margem
    expandida e recortada). O instalador deve ser avisado.
    """
    x1, y1, x2, y2 = bbox
    fw, fh = frame_size
    edges = []
    if x1 <= margin_px:
        edges.append("left")
    if y1 <= margin_px:
        edges.append("top")
    if x2 >= fw - 1 - margin_px:
        edges.append("right")
    if y2 >= fh - 1 - margin_px:
        edges.append("bottom")
    return edges
