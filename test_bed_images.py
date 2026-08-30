"""
Teste de deteccao de cama sobre imagens estaticas.
Simula o processo de calibracao usando imagens salvas em teste_camera/
(frames PUROS da camera, sem overlays do dashboard — screenshots do sistema
confundem o YOLO).

Reproduz o MESMO pre-processamento da calibracao em producao
(main.prepare_bed_frames: frame normalizado para o COCO + frame cru para
histEq/raw/ASETO). Antes este script chamava detect_bed() sem raw_frame e
sem normalizacao, e o resultado offline nao batia com o RPi.

Uso: python test_bed_images.py [pasta_ou_imagens...]
"""

import glob
import os
import sys

import cv2

from config import (
    BED_DETECTION_SENSITIVITY,
    CALIBRATION_MAX_VARIANCE,
    CALIBRATION_MIN_CONSISTENT,
    CALIBRATION_MIN_DETECTION_RATE,
    FLIP_HORIZONTAL,
    YOLO_BED_MODEL,
)
from ultralytics import YOLO

from modules.bed_detector import BedDetector
from modules.bed_zone import bbox_touches_edges

from main import _calibrate_consistency, _calibrate_standard, prepare_bed_frames

IMAGE_DIR = "teste_camera"
EXTENSIONS = ("*.jpg", "*.jpeg", "*.png")


def _collect_images(args: list) -> list:
    if not args:
        args = [IMAGE_DIR]
    images = []
    for arg in args:
        if os.path.isdir(arg):
            for ext in EXTENSIONS:
                images.extend(glob.glob(os.path.join(arg, ext)))
        else:
            images.append(arg)
    # Ignora saidas de execucoes anteriores
    images = [p for p in images if "_det" not in os.path.basename(p)
              and "resultado" not in os.path.basename(p)]
    return sorted(set(images))


def main():
    images = _collect_images(sys.argv[1:])

    if not images:
        print(f"Nenhuma imagem encontrada em {IMAGE_DIR}/")
        print("Coloque frames .jpg/.png nessa pasta (ou passe caminhos) e rode novamente.")
        sys.exit(1)

    print("=" * 60)
    print("TESTE DE DETECCAO DE CAMA - IMAGENS ESTATICAS")
    print("=" * 60)
    print(f"Modelo: {YOLO_BED_MODEL}")
    print(f"Sensibilidade: {BED_DETECTION_SENSITIVITY} "
          f"(x{BedDetector.sensitivity_multiplier(BED_DETECTION_SENSITIVITY):.2f})")
    print(f"Imagens encontradas: {len(images)}")
    print(f"Flip horizontal: {FLIP_HORIZONTAL}")
    print()

    print("Carregando modelo YOLO...")
    model = YOLO(YOLO_BED_MODEL)
    bed_detector = BedDetector(model)
    detections = []
    strategies = []
    frame_size = None

    for i, img_path in enumerate(images):
        frame = cv2.imread(img_path)
        if frame is None:
            print(f"[{i+1}/{len(images)}] ERRO ao ler: {img_path}")
            continue

        if FLIP_HORIZONTAL:
            frame = cv2.flip(frame, 1)

        h, w = frame.shape[:2]
        frame_size = (w, h)
        print(f"\n--- [{i+1}/{len(images)}] {img_path} ({w}x{h}) ---")

        # Mesmo caminho da calibracao em producao
        norm_frame, raw_frame = prepare_bed_frames(frame)
        bbox = bed_detector.detect_bed(norm_frame, raw_frame=raw_frame, diagnostic=True)

        if bbox:
            detections.append(bbox)
            strategies.append(bed_detector.detected_strategy)
            print(f"  >> Detectada: bbox={bbox} via '{bed_detector.detected_strategy}'")
        else:
            print(f"  >> Nenhuma cama detectada")

    print("\n" + "=" * 60)
    print("RESULTADO DA CALIBRACAO")
    print("=" * 60)
    print(f"Deteccoes: {len(detections)}/{len(images)} imagens")
    if strategies:
        counts = {s: strategies.count(s) for s in set(strategies)}
        print(f"Estrategias vencedoras: {counts}")

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
        if frame_size:
            edges = bbox_touches_edges(result, frame_size)
            if edges:
                print(f"  AVISO: cama encostada na(s) borda(s): {', '.join(edges)} "
                      f"- zona de queda fora do enquadramento")
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
            out_dir = os.path.dirname(images[-1]) or "."
            out_path = os.path.join(out_dir, "resultado_calibracao.jpg")
            cv2.imwrite(out_path, last_frame)
            print(f"\n  Imagem com bbox salva em: {out_path}")


if __name__ == "__main__":
    main()
