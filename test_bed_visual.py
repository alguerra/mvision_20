"""
Gera imagens anotadas com resultado da deteccao de cama.
Salva cada imagem com bbox marcado ou mensagem de nao-reconhecimento.
"""

import glob
import os

import cv2
from ultralytics import YOLO

from config import FLIP_HORIZONTAL, YOLO_BED_MODEL
from modules.bed_detector import BedDetector

IMAGE_DIR = "teste_camera"


def main():
    images = sorted(
        glob.glob(f"{IMAGE_DIR}/*.jpg")
        + glob.glob(f"{IMAGE_DIR}/*.png")
        + glob.glob(f"{IMAGE_DIR}/*.jpeg")
    )
    images = [f for f in images if "resultado" not in f and "_det" not in f]

    if not images:
        print(f"Nenhuma imagem em {IMAGE_DIR}/")
        return

    print(f"Carregando modelo {YOLO_BED_MODEL}...")
    model = YOLO(YOLO_BED_MODEL)
    bed_detector = BedDetector(model)

    for img_path in images:
        frame = cv2.imread(img_path)
        if frame is None:
            continue

        if FLIP_HORIZONTAL:
            frame = cv2.flip(frame, 1)

        bbox = bed_detector.detect_bed(frame, diagnostic=True)

        base, ext = os.path.splitext(img_path)
        out_path = f"{base}_det{ext}"

        if bbox:
            x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
            label = "CAMA RECONHECIDA"
            color = (0, 255, 0)
            cv2.putText(frame, label, (x1, y1 - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4)
            cv2.putText(frame, label, (x1, y1 - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
            coords = f"({x1},{y1})-({x2},{y2})"
            cv2.putText(frame, coords, (x1, y2 + 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
            cv2.putText(frame, coords, (x1, y2 + 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            print(f"  {img_path} -> RECONHECIDA bbox={coords}")
        else:
            label = "CAMA NAO RECONHECIDA"
            color = (0, 0, 255)
            h, w = frame.shape[:2]
            cv2.putText(frame, label, (w // 2 - 220, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4)
            cv2.putText(frame, label, (w // 2 - 220, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
            print(f"  {img_path} -> NAO RECONHECIDA")

        if FLIP_HORIZONTAL:
            frame = cv2.flip(frame, 1)

        cv2.imwrite(out_path, frame)
        print(f"    Salva em: {out_path}")


if __name__ == "__main__":
    main()
