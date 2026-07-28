"""
Exporta o yolov8n-pose para NCNN e valida a paridade dos keypoints.

RODAR NO NOTEBOOK (nao no Raspberry Pi):

    python tools/export_ncnn_pose.py [pasta_com_imagens_de_teste]

- Exporta yolov8n-pose.pt -> yolov8n-pose_ncnn_model/ (imgsz do config)
- Se uma pasta de imagens for informada (frames reais do leito, com pessoas),
  roda os DOIS backends em cada imagem e compara deteccoes e keypoints.
- Criterio de aprovacao: diferenca media de keypoints < 2.0 px.

Depois de aprovado, copie a pasta yolov8n-pose_ncnn_model/ inteira para
/mvision no dispositivo (junto do codigo). Com YOLO_POSE_BACKEND="auto"
(default), o sistema passa a usar NCNN automaticamente. Rollback: apagar a
pasta no dispositivo ou definir YOLO_POSE_BACKEND="pt".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from ultralytics import YOLO

from config import (
    YOLO_POSE_CONFIDENCE,
    YOLO_POSE_IMGSZ,
    YOLO_POSE_IOU,
    YOLO_POSE_MAX_DET,
    YOLO_POSE_MODEL,
    YOLO_POSE_NCNN_DIR,
)

PARITY_MEAN_PX_MAX = 2.0    # Paridade PLENA: ativacao automatica OK
PARITY_MEAN_PX_PARTIAL = 10.0  # Paridade PARCIAL: exige validacao funcional em campo
MATCH_IOU_MIN = 0.5         # Pareamento de deteccoes entre backends


def _predict(model, image_path):
    results = model.predict(
        str(image_path),
        conf=YOLO_POSE_CONFIDENCE,
        iou=YOLO_POSE_IOU,
        imgsz=YOLO_POSE_IMGSZ,
        max_det=YOLO_POSE_MAX_DET,
        classes=[0],
        verbose=False,
    )
    dets = []
    if results and results[0].keypoints is not None and results[0].boxes is not None:
        kps = results[0].keypoints
        boxes = results[0].boxes
        n = min(len(kps.xy), len(boxes))
        for i in range(n):
            dets.append({
                "box": boxes.xyxy[i].cpu().numpy(),
                "kp": kps.xy[i].cpu().numpy(),
            })
    return dets


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def main():
    root = Path(__file__).parent.parent
    pt_path = root / YOLO_POSE_MODEL
    ncnn_dir = root / YOLO_POSE_NCNN_DIR

    if not pt_path.exists():
        print(f"ERRO: {pt_path} nao encontrado (rode 'git lfs pull')")
        sys.exit(1)

    # 1. Export
    print(f"[1/3] Exportando {YOLO_POSE_MODEL} para NCNN (imgsz={YOLO_POSE_IMGSZ})...")
    model_pt = YOLO(str(pt_path))
    if not (ncnn_dir.is_dir() and any(ncnn_dir.glob("*.param"))):
        model_pt.export(format="ncnn", imgsz=YOLO_POSE_IMGSZ)
        print(f"    Exportado em {ncnn_dir}/")
    else:
        print(f"    {ncnn_dir}/ ja existe - pulando export (apague a pasta para reexportar)")

    # 2. Smoke test do backend NCNN
    print("[2/3] Carregando backend NCNN...")
    model_ncnn = YOLO(str(ncnn_dir))
    dummy = np.full((480, 640, 3), 128, dtype=np.uint8)
    model_ncnn.predict(dummy, imgsz=YOLO_POSE_IMGSZ, verbose=False)
    print("    NCNN carrega e infere - OK")

    # 3. Paridade com imagens reais
    if len(sys.argv) < 2:
        print("[3/3] AVISO: nenhuma pasta de imagens informada - paridade NAO validada.")
        print("       Rode: python tools/export_ncnn_pose.py <pasta_com_frames_do_leito>")
        print("       So ative em producao apos a paridade passar.")
        return

    img_dir = Path(sys.argv[1])
    images = sorted(
        [p for ext in ("*.jpg", "*.jpeg", "*.png") for p in img_dir.glob(ext)]
    )
    if not images:
        print(f"[3/3] ERRO: nenhuma imagem em {img_dir}")
        sys.exit(1)

    print(f"[3/3] Comparando backends em {len(images)} imagens...")
    diffs = []
    det_mismatch = 0
    for img in images:
        dets_pt = _predict(model_pt, img)
        dets_ncnn = _predict(model_ncnn, img)
        if len(dets_pt) != len(dets_ncnn):
            det_mismatch += 1
        for d_pt in dets_pt:
            best = None
            best_iou = MATCH_IOU_MIN
            for d_nc in dets_ncnn:
                v = _iou(d_pt["box"], d_nc["box"])
                if v >= best_iou:
                    best_iou = v
                    best = d_nc
            if best is not None:
                # Distancia media por keypoint (px), ignorando kp em (0,0)
                mask = (d_pt["kp"].sum(axis=1) > 0) & (best["kp"].sum(axis=1) > 0)
                if mask.any():
                    d = np.linalg.norm(d_pt["kp"][mask] - best["kp"][mask], axis=1)
                    diffs.append(float(d.mean()))

    if not diffs:
        print("    ERRO: nenhuma deteccao pareada - use imagens com pessoas visiveis")
        sys.exit(1)

    mean_diff = float(np.mean(diffs))
    max_diff = float(np.max(diffs))
    print(f"    Deteccoes pareadas: {len(diffs)} | contagem divergente em {det_mismatch}/{len(images)} imagens")
    print(f"    Diferenca de keypoints: media {mean_diff:.2f} px | pior caso {max_diff:.2f} px")

    if mean_diff < PARITY_MEAN_PX_MAX:
        print(f"\nPARIDADE PLENA (media < {PARITY_MEAN_PX_MAX} px).")
        print(f"Copie {YOLO_POSE_NCNN_DIR}/ para /mvision e use YOLO_POSE_BACKEND='auto'.")
    elif mean_diff < PARITY_MEAN_PX_PARTIAL:
        print(f"\nPARIDADE PARCIAL (media {mean_diff:.1f} px, entre {PARITY_MEAN_PX_MAX} e {PARITY_MEAN_PX_PARTIAL}).")
        print("Provavelmente equivalente na FSM (margens da cama sao 40-140px), mas NAO comprovado.")
        print("Ative APENAS no leito de teste (YOLO_POSE_BACKEND='ncnn'), rode a tabela")
        print("funcional da Etapa 8 do INSTALACAO.md e compare 1 noite de logs antes de")
        print("promover para 'auto' em producao.")
    else:
        print(f"\nPARIDADE REPROVADA (media >= {PARITY_MEAN_PX_PARTIAL} px).")
        print("NAO ative NCNN. Revalide o export/versao do ultralytics.")
        sys.exit(1)


if __name__ == "__main__":
    main()
