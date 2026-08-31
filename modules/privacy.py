"""
Anonimizacao visual — circulo solido sobre rosto/cabeca de TODA pessoa exibida.

Garantia de privacidade na apresentacao: nenhuma imagem renderizada (monitor
HDMI, painel web, imagens de alerta salvas) permite identificar paciente ou
acompanhante. A mascara e aplicada DEPOIS dos keypoints serem desenhados, de
modo que os marcadores de cabeca tambem ficam cobertos.

A inferencia em si nao muda: o modelo de pose continua vendo o frame original
(precisa dos keypoints da cabeca para a propria mascara e para a FSM); o que
nunca sai do processo e a imagem com rosto visivel.
"""

from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

# Indices COCO-17 usados pelo yolov8-pose
HEAD_KP_INDICES = (0, 1, 2, 3, 4)   # nariz, olhos, orelhas
SHOULDER_KP_INDICES = (5, 6)

MASK_COLOR = (90, 90, 90)           # cinza neutro, solido
MASK_MIN_RADIUS = 14                # px; nunca menor que isto
KP_CONF_MIN = 0.25


def head_circle(
    keypoints_xy: np.ndarray,
    keypoints_conf: Optional[np.ndarray] = None,
    bbox: Optional[Sequence[float]] = None,
) -> Optional[Tuple[int, int, int]]:
    """
    Estima o circulo (cx, cy, raio) que cobre rosto/cabeca de UMA pessoa.

    Ordem de robustez:
    1. Keypoints de cabeca visiveis -> centro no meio deles, raio pela
       dispersao e pela largura dos ombros (o rosto e ~metade da distancia
       entre ombros; usamos folga generosa).
    2. So ombros visiveis -> circulo acima do ponto medio dos ombros.
    3. Nada visivel mas ha bbox -> cobre o topo do bbox (pessoa de costas ou
       keypoints suprimidos; melhor cobrir demais que de menos).
    Retorna None apenas sem keypoints E sem bbox.
    """
    if keypoints_conf is None:
        keypoints_conf = np.ones(len(keypoints_xy))

    def visible(indices):
        pts = []
        for i in indices:
            if i < len(keypoints_xy) and keypoints_conf[i] >= KP_CONF_MIN:
                x, y = keypoints_xy[i]
                if x > 0 or y > 0:  # (0,0) = keypoint ausente no ultralytics
                    pts.append((float(x), float(y)))
        return pts

    head_pts = visible(HEAD_KP_INDICES)
    shoulder_pts = visible(SHOULDER_KP_INDICES)

    shoulder_dist = None
    if len(shoulder_pts) == 2:
        shoulder_dist = float(np.hypot(
            shoulder_pts[0][0] - shoulder_pts[1][0],
            shoulder_pts[0][1] - shoulder_pts[1][1],
        ))

    if head_pts:
        cx = float(np.mean([p[0] for p in head_pts]))
        cy = float(np.mean([p[1] for p in head_pts]))
        spread = max(
            (np.hypot(p[0] - cx, p[1] - cy) for p in head_pts), default=0.0
        )
        radius = spread * 1.6
        if shoulder_dist:
            radius = max(radius, 0.55 * shoulder_dist)
        elif bbox is not None:
            radius = max(radius, 0.12 * max(bbox[2] - bbox[0], bbox[3] - bbox[1]))
        return int(cx), int(cy), max(MASK_MIN_RADIUS, int(radius))

    if shoulder_dist:
        mid_x = (shoulder_pts[0][0] + shoulder_pts[1][0]) / 2.0
        mid_y = (shoulder_pts[0][1] + shoulder_pts[1][1]) / 2.0
        # cabeca ~acima do meio dos ombros (aproximacao para pessoa ereta;
        # deitada, o raio generoso compensa a incerteza de direcao)
        radius = max(MASK_MIN_RADIUS, int(0.75 * shoulder_dist))
        return int(mid_x), int(mid_y - 0.5 * shoulder_dist), radius

    if bbox is not None:
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            return None
        # sem nenhum keypoint: cobre a faixa superior do bbox
        radius = max(MASK_MIN_RADIUS, int(0.30 * min(w, h)))
        return int((x1 + x2) / 2), int(y1 + radius), radius

    return None


def apply_face_privacy(
    frame: np.ndarray,
    persons: List[Tuple[np.ndarray, Optional[np.ndarray], Optional[Sequence[float]]]],
) -> np.ndarray:
    """
    Desenha o circulo de anonimizacao para cada pessoa da lista.

    Args:
        frame: Frame BGR (modificado in-place e retornado).
        persons: Lista de (keypoints_xy, keypoints_conf, bbox) — TODAS as
            deteccoes mantidas, paciente e acompanhantes.
    """
    for kp_xy, kp_conf, bbox in persons:
        circle = head_circle(kp_xy, kp_conf, bbox)
        if circle is None:
            continue
        cx, cy, r = circle
        cv2.circle(frame, (cx, cy), r, MASK_COLOR, -1)
        cv2.circle(frame, (cx, cy), r, (40, 40, 40), 2)
    return frame
