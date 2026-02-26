"""
Diagnostico de deteccao de cama - compara multiplos modelos YOLO.
Testa yolov8s, yolov8m, yolov8l e yolov8x para ver qual detecta
a cama neste angulo de camera.

Uso: python diag_bed.py
"""

import cv2
import numpy as np
from ultralytics import YOLO

from config import (
    BED_MIN_AREA_RATIO,
    CAMERA_BACKEND,
    CAMERA_INDEX,
    FLIP_HORIZONTAL,
    YOLO_BED_MODEL,
)
from modules.camera import create_camera

NUM_FRAMES = 5
CONF_THRESHOLD = 0.01  # Muito baixo para ver tudo

# Modelos a testar (em ordem de tamanho crescente)
MODELS_TO_TEST = [
    YOLO_BED_MODEL,   # yolov8s.pt (atual)
    "yolov8m.pt",     # medium
    "yolov8l.pt",     # large
    "yolov8x.pt",     # extra-large
]

# Classes relevantes para cama
BED_CLASSES = {"bed", "couch", "bench", "sofa", "chair", "dining table", "toilet", "sink"}
# Classes que o sistema aceita como cama
TARGET_CLASSES = {"bed", "couch", "bench"}


def run_diagnostic(model, model_name, camera, frame_area):
    """Roda diagnostico com um modelo especifico."""
    print(f"\n{'='*60}")
    print(f"MODELO: {model_name}")
    print(f"{'='*60}")

    # Descarta frames para estabilizar
    for _ in range(5):
        camera.read()

    bed_detections = []  # Coleta deteccoes bed/couch/bench

    for i in range(NUM_FRAMES):
        ret, frame = camera.read()
        if not ret or frame is None:
            print(f"Frame {i+1}: FALHA na captura")
            continue

        if FLIP_HORIZONTAL:
            frame = cv2.flip(frame, 1)

        results = model.predict(frame, conf=CONF_THRESHOLD, verbose=False)

        print(f"\n--- Frame {i+1}/{NUM_FRAMES} ---")

        if len(results) == 0 or results[0].boxes is None or len(results[0].boxes) == 0:
            print("  Nenhuma deteccao")
            continue

        boxes = results[0].boxes

        # Filtra e ordena apenas bed-related por confianca
        detections = []
        for j in range(len(boxes)):
            cls_id = int(boxes.cls[j])
            cls_name = model.names[cls_id]
            if cls_name.lower() not in BED_CLASSES:
                continue

            bbox = boxes.xyxy[j].cpu().numpy()
            conf = float(boxes.conf[j])
            x1, y1, x2, y2 = bbox
            det_area = (x2 - x1) * (y2 - y1)
            area_pct = (det_area / frame_area) * 100

            detections.append((cls_name, cls_id, conf, area_pct, bbox))

            # Marca se eh classe-alvo com conf razoavel
            if cls_name.lower() in TARGET_CLASSES and conf >= 0.05:
                bed_detections.append((cls_name, conf, area_pct, i + 1))

        detections.sort(key=lambda d: d[2], reverse=True)

        if not detections:
            print("  Nenhuma deteccao bed-related")
            continue

        # Mostra top 10 bed-related
        for cls_name, cls_id, conf, area_pct, bbox in detections[:10]:
            x1, y1, x2, y2 = bbox
            area_ok = "OK" if area_pct >= BED_MIN_AREA_RATIO * 100 else "PEQUENO"
            star = " ***" if cls_name.lower() in TARGET_CLASSES else ""
            print(f"  {cls_name:15s} conf={conf:.3f} area={area_pct:5.1f}% [{area_ok:7s}] "
                  f"bbox=({int(x1):3d},{int(y1):3d},{int(x2):3d},{int(y2):3d}){star}")

        # Salva frame do ultimo para referencia
        if i == NUM_FRAMES - 1 and frame is not None:
            out_path = f"data/diag_{model_name.replace('.pt', '')}.jpg"
            cv2.imwrite(out_path, frame)

    # Resumo do modelo
    print(f"\n>>> RESUMO {model_name}: ", end="")
    if bed_detections:
        print(f"{len(bed_detections)} deteccoes bed/couch/bench:")
        for cls_name, conf, area_pct, frame_num in bed_detections:
            print(f"    Frame {frame_num}: {cls_name} conf={conf:.3f} area={area_pct:.1f}%")
    else:
        print("NENHUMA deteccao como 'bed', 'couch' ou 'bench'")

    return bed_detections


def main():
    print("=" * 60)
    print("DIAGNOSTICO DE DETECCAO DE CAMA - MULTI-MODELO")
    print("=" * 60)

    # Abre camera
    print(f"\nAbrindo camera {CAMERA_INDEX} (backend={CAMERA_BACKEND})...")
    camera = create_camera(CAMERA_INDEX, backend=CAMERA_BACKEND)
    if not camera.open():
        print("ERRO: Nao foi possivel abrir a camera")
        return
    camera.set_resolution(640, 480)
    w, h = camera.get_resolution()
    print(f"Camera aberta: {w}x{h}")

    # Descarta primeiros frames (auto-exposicao)
    print("Descartando 10 frames iniciais (auto-exposicao)...")
    for _ in range(10):
        camera.read()

    frame_area = w * h
    print(f"Conf threshold: {CONF_THRESHOLD}")
    print(f"Area minima configurada: {BED_MIN_AREA_RATIO * 100:.1f}%")

    # Testa cada modelo
    results_summary = {}
    for model_path in MODELS_TO_TEST:
        print(f"\nCarregando {model_path}...")
        try:
            model = YOLO(model_path)
            detections = run_diagnostic(model, model_path, camera, frame_area)
            results_summary[model_path] = detections
        except Exception as e:
            print(f"  ERRO ao carregar {model_path}: {e}")
            results_summary[model_path] = None

    camera.release()

    # Resumo final
    print("\n" + "=" * 60)
    print("RESULTADO FINAL")
    print("=" * 60)
    best_model = None
    best_conf = 0

    for model_path, detections in results_summary.items():
        if detections is None:
            status = "ERRO (modelo nao disponivel)"
        elif detections:
            max_conf = max(d[1] for d in detections)
            count = len(detections)
            status = f"DETECTOU {count}x bed/couch/bench (max conf={max_conf:.3f})"
            if max_conf > best_conf:
                best_conf = max_conf
                best_model = model_path
        else:
            status = "NAO detectou bed/couch/bench"
        print(f"  {model_path:20s} -> {status}")

    if best_model:
        print(f"\n>>> RECOMENDACAO: usar {best_model} (melhor conf={best_conf:.3f})")
        print(f"    Altere YOLO_BED_MODEL em config.py para '{best_model}'")
    else:
        print("\n>>> NENHUM modelo detectou a cama como bed/couch/bench.")
        print("    Opcoes: calibracao manual ou adicionar classes ao detector.")


if __name__ == "__main__":
    main()
