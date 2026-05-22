"""
Teste de deteccao de cama sobre imagens estaticas.
Simula o processo de calibracao usando imagens salvas em data/test_images/.

Uso: python test_bed_images.py
"""

import glob
import sys

import cv2
import numpy as np

from config import (
    BED_MIN_AREA_RATIO,
    BED_MAX_AREA_RATIO,
    CALIBRATION_CONSISTENCY_MAX_DIST,
    CALIBRATION_CONSISTENCY_VARIANCE,
    CALIBRATION_FRAMES,
    CALIBRATION_MAX_VARIANCE,
    CALIBRATION_MIN_CONSISTENT,
    CALIBRATION_MIN_DETECTION_RATE,
    FLIP_HORIZONTAL,
    YOLO_BED_MODEL,
)
from ultralytics import YOLO

from modules.bed_detector import BedDetector

from main import _calibrate_consistency, _calibrate_standard

IMAGE_DIR = "teste_camera"


def main():
    images = sorted(
        glob.glob(f"{IMAGE_DIR}/*.jpg")
        + glob.glob(f"{IMAGE_DIR}/*.png")
        + glob.glob(f"{IMAGE_DIR}/*.jpeg")
    )

    if not images:
        print(f"Nenhuma imagem encontrada em {IMAGE_DIR}/")
        print("Coloque imagens .jpg/.png nessa pasta e rode novamente.")
        sys.exit(1)

    print("=" * 60)
    print("TESTE DE DETECCAO DE CAMA - IMAGENS ESTATICAS")
    print("=" * 60)
    print(f"Modelo: {YOLO_BED_MODEL}")
    print(f"Imagens encontradas: {len(images)}")
    print(f"Flip horizontal: {FLIP_HORIZONTAL}")
    print()

    print("Carregando modelo YOLO...")
    model = YOLO(YOLO_BED_MODEL)
    bed_detector = BedDetector(model)
    detections = []

    for i, img_path in enumerate(images):
        frame = cv2.imread(img_path)
        if frame is None:
            print(f"[{i+1}/{len(images)}] ERRO ao ler: {img_path}")
            continue

        if FLIP_HORIZONTAL:
            frame = cv2.flip(frame, 1)

        h, w = frame.shape[:2]
        print(f"\n--- [{i+1}/{len(images)}] {img_path} ({w}x{h}) ---")

        bbox = bed_detector.detect_bed(frame, diagnostic=True)

        if bbox:
            detections.append(bbox)
            print(f"  >> Detectada: bbox={bbox}")
        else:
            print(f"  >> Nenhuma cama detectada")

    print("\n" + "=" * 60)
    print("RESULTADO DA CALIBRACAO")
    print("=" * 60)
    print(f"Deteccoes: {len(detections)}/{len(images)} imagens")

    if not detections:
        print("Nenhuma deteccao - calibracao impossivel.")
        return

    num_frames = len(images)
    min_detections = int(num_frames * CALIBRATION_MIN_DETECTION_RATE)

    print(f"\nMinimo padrao: {min_detections} deteccoes (taxa {CALIBRATION_MIN_DETECTION_RATE})")
    print(f"Minimo consistencia: {CALIBRATION_MIN_CONSISTENT} deteccoes")

    # Caminho A: padrao
    print(f"\n--- Caminho A: Calibracao Padrao ---")
    if len(detections) >= min_detections:
        result_a = _calibrate_standard(detections, num_frames, min_detections, CALIBRATION_MAX_VARIANCE)
    else:
        print(f"    Insuficiente: {len(detections)} < {min_detections}")
        result_a = None

    # Caminho B: consistencia
    print(f"\n--- Caminho B: Calibracao por Consistencia ---")
    if len(detections) >= CALIBRATION_MIN_CONSISTENT:
        result_b = _calibrate_consistency(detections)
    else:
        print(f"    Insuficiente: {len(detections)} < {CALIBRATION_MIN_CONSISTENT}")
        result_b = None

    # Resultado final
    print(f"\n{'=' * 60}")
    print("DECISAO FINAL")
    print(f"{'=' * 60}")
    result = result_a if result_a is not None else result_b
    if result is not None:
        path_used = "PADRAO" if result_a is not None else "CONSISTENCIA"
        print(f"  Calibracao ACEITA via caminho {path_used}")
        print(f"  BBox final: {result}")
    else:
        print("  Calibracao FALHOU em ambos os caminhos")
        print("  Verifique os logs acima para diagnostico")

    # Visualizacao
    if result is not None and images:
        last_frame = cv2.imread(images[-1])
        if last_frame is not None:
            if FLIP_HORIZONTAL:
                last_frame = cv2.flip(last_frame, 1)
            x1, y1, x2, y2 = result
            cv2.rectangle(last_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(last_frame, "BED", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            out_path = f"{IMAGE_DIR}/resultado_calibracao.jpg"
            cv2.imwrite(out_path, last_frame)
            print(f"\n  Imagem com bbox salva em: {out_path}")


if __name__ == "__main__":
    main()
