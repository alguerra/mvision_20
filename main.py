"""
Sistema de Monitoramento de Quedas Hospitalares
Ponto de entrada e loop principal.

Utiliza YOLOv8-Pose para deteccao de keypoints do paciente e analise
de pose em relacao a area da cama para prevencao de quedas.

Estados do paciente:
    AGUARDANDO - Aguardando paciente ser detectado na cama
    MONITORANDO - Paciente na cama, monitoramento ativo
    RISCO_POTENCIAL - Partes do corpo fora da cama
    PACIENTE_FORA - Paciente completamente fora da cama
    ACOMPANHADO - Mais de uma pessoa detectada, paciente acompanhado

Controles:
    Q - Sair do programa
    R - Resetar maquina de estados
"""

import logging
import os
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

# Suprime warnings do OpenCV e ultralytics sobre fonts
warnings.filterwarnings("ignore", message=".*font.*", category=UserWarning)

# No Linux sem DISPLAY, configura Qt para modo offscreen
# Isso evita erros de GUI quando nao ha monitor conectado
import platform
if platform.system() == "Linux" and not os.environ.get("DISPLAY"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Sistema 100% offline: impede qualquer tentativa de download do ultralytics
# (ex: quando um .pt esta corrompido/ponteiro LFS, ele tentaria baixar da internet)
os.environ.setdefault("YOLO_OFFLINE", "True")
os.environ.setdefault("ULTRALYTICS_OFFLINE", "True")
os.environ.setdefault("YOLO_AUTOINSTALL", "False")

from ultralytics import YOLO

from config import (
    BED_STANDBY_RETRY_SECONDS,
    COMPANION_ANALYSIS_ENABLED,
    PATIENT_ASSOC_MAX_JUMP_RATIO,
    CALIBRATION_CONSISTENCY_MAX_DIST,
    CALIBRATION_CONSISTENCY_VARIANCE,
    CALIBRATION_FRAMES,
    CALIBRATION_MAX_VARIANCE,
    CALIBRATION_MIN_CONSISTENT,
    CALIBRATION_MIN_DETECTION_RATE,
    CALIBRATION_SUCCESS_DISPLAY_SECONDS,
    CAMERA_BACKEND,
    CAMERA_INDEX,
    DEV_MODE,
    DEV_SKIP_BED_DETECTION,
    DISPLAY_WAIT_TIMEOUT,
    FLIP_HORIZONTAL,
    FRAME_DELAY_SECONDS,
    POSE_CONFIDENCE_HIGH,
    POSE_CONFIDENCE_MIN,
    POSE_FRAMES_PATIENT_DETECTED,
    POSE_FRAMES_TO_CONFIRM,
    WINDOW_NAME,
    YOLO_BED_MODEL,
    YOLO_POSE_CONFIDENCE,
    YOLO_POSE_IMGSZ,
    YOLO_POSE_IOU,
    YOLO_POSE_MAX_DET,
    YOLO_POSE_MODEL,
)
from gui.display import DisplayManager
from modules.alert_logger import AlertLogger
from modules.bed_detector import BedDetector
from modules.camera import CameraBase, create_camera, get_platform_info, IS_LINUX, wait_for_display
from modules.environment import get_environment_id
from modules.gpio_alerts import GPIOAlertManager
from modules.patient_monitor import PatientMonitor
from modules.pose_analyzer import BodyPoints, PoseAnalyzer, PoseStateMachineEMA, PositionAnalysis
from modules.state_machine import PatientPoseState, SystemState


# =============================================================================
# CONFIGURACOES DE RESILIENCIA
# =============================================================================

# Arquivo de heartbeat para watchdog (Linux/Raspberry Pi)
HEARTBEAT_FILE = "/tmp/hospital-monitor-heartbeat"
HEARTBEAT_INTERVAL = 30  # Segundos entre heartbeats

# Status do monitor para o painel web (/tmp = tmpfs, zero desgaste de SD).
# Sem isso, um monitor em loop de reinicializacao (ex: camera morta) parece
# "ativo" no painel e ninguem percebe que o leito esta sem cobertura.
STATUS_FILE = "/tmp/mvision_status.json"

# Tentativas de reinicializacao
MAX_INIT_RETRIES = 10  # Aumentado para maior resiliencia no Raspberry Pi
INIT_RETRY_DELAY = 5   # Segundos entre tentativas (reduzido para recuperar mais rapido)

# Tentativas de recuperacao de erro no loop principal
MAX_CONSECUTIVE_ERRORS = 30  # Aumentado para dar mais tempo de recuperacao
ERROR_RECOVERY_DELAY = 1  # Segundos para aguardar antes de tentar novamente

# Configura logging de erros
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("HospitalMonitor")


# =============================================================================
# FUNCOES DE RESILIENCIA
# =============================================================================

def normalize_frame_for_ir(frame: np.ndarray) -> np.ndarray:
    """Corrige balanco de branco e contraste para cameras IR.
    1) Equaliza medias dos canais BGR (remove tonalidade roxa)
    2) Aplica CLAHE no canal L (melhora contraste local)"""
    result = frame.copy()
    avg_per_channel = result.mean(axis=(0, 1))
    global_avg = avg_per_channel.mean()
    for i in range(3):
        if avg_per_channel[i] > 0:
            result[:, :, i] = np.clip(
                result[:, :, i] * (global_avg / avg_per_channel[i]), 0, 255
            ).astype(np.uint8)
    lab = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _notify_systemd(message: bytes) -> None:
    """Envia notificação ao systemd via NOTIFY_SOCKET."""
    if not IS_LINUX:
        return
    try:
        import socket
        addr = os.environ.get("NOTIFY_SOCKET")
        if addr:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sock.connect(addr)
                sock.sendall(message)
            finally:
                sock.close()
    except Exception:
        pass


def send_heartbeat() -> None:
    """
    Envia heartbeat para o watchdog do sistema.
    Notifica o systemd watchdog e atualiza arquivo de heartbeat.
    """
    if not IS_LINUX:
        return

    _notify_systemd(b"WATCHDOG=1")

    try:
        Path(HEARTBEAT_FILE).touch()
    except Exception:
        pass


def write_status_file(state: str, person_count: int = 0) -> None:
    """Publica estado atual do monitor para o painel web (via tmpfs)."""
    if not IS_LINUX:
        return
    try:
        from modules.atomic_io import atomic_write_json
        atomic_write_json(STATUS_FILE, {
            "timestamp": time.time(),
            "state": state,
            "person_count": person_count,
        })
    except Exception:
        pass


def log_exception(context: str, exc: Exception) -> None:
    """
    Registra excecao no log com contexto.

    Args:
        context: Descricao do contexto onde ocorreu o erro
        exc: Excecao capturada
    """
    logger.error(f"{context}: {type(exc).__name__}: {exc}")
    logger.debug(traceback.format_exc())


def safe_cleanup(camera: Optional[CameraBase], display: Optional[DisplayManager], gpio_manager: Optional['GPIOAlertManager'] = None) -> None:
    """
    Libera recursos de forma segura.

    Args:
        camera: Instancia da camera (pode ser None)
        display: Instancia do display (pode ser None)
        gpio_manager: Instancia do gerenciador GPIO (pode ser None)
    """
    try:
        if camera is not None:
            camera.release()
    except Exception:
        pass

    try:
        if display is not None:
            display.close()
    except Exception:
        pass

    # cv2.destroyAllWindows() so eh necessario no modo GUI
    # e ja eh chamado pelo display.close() - evita duplicacao
    # que pode causar problemas no modo headless

    try:
        if gpio_manager is not None:
            gpio_manager.cleanup()
    except Exception:
        pass


# =============================================================================
# FUNCOES PRINCIPAIS
# =============================================================================

def _find_consistent_clusters(
    bboxes: np.ndarray,
    max_dist: float,
) -> list:
    """
    Agrupa deteccoes por proximidade espacial (complete-linkage).
    Cada bbox so entra no cluster se proximo de TODOS os membros existentes.
    """
    n = len(bboxes)
    assigned = [False] * n
    clusters = []

    for i in range(n):
        if assigned[i]:
            continue
        cluster = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            close_to_all = True
            for k in cluster:
                dist = np.max(np.abs(bboxes[j] - bboxes[k]))
                if dist > max_dist:
                    close_to_all = False
                    break
            if close_to_all:
                cluster.append(j)
                assigned[j] = True
        clusters.append(cluster)

    return clusters


def _calibrate_standard(
    detections: list,
    num_frames: int,
    min_detections: int,
    max_variance: float,
) -> Optional[Tuple[int, int, int, int]]:
    """Calibracao padrao: filtra outliers via IQR, aceita se variancia baixa."""
    bboxes = np.array(detections)
    median_bbox = np.median(bboxes, axis=0)
    q1 = np.percentile(bboxes, 25, axis=0)
    q3 = np.percentile(bboxes, 75, axis=0)
    iqr = q3 - q1
    margin = np.maximum(iqr * 1.5, 30)
    lower = median_bbox - margin
    upper = median_bbox + margin
    mask = np.all((bboxes >= lower) & (bboxes <= upper), axis=1)
    filtered = bboxes[mask]

    n_removed = len(bboxes) - len(filtered)
    if n_removed > 0:
        print(f"    [padrao] Filtrados {n_removed} outliers de {len(bboxes)} deteccoes")

    if len(filtered) < min_detections:
        print(f"    [padrao] Falhou: apenas {len(filtered)}/{num_frames} deteccoes apos filtro")
        return None

    variance = filtered.std(axis=0).max()

    if variance > max_variance:
        print(f"    [padrao] Falhou: variancia {variance:.1f} > {max_variance}")
        return None

    result_bbox = tuple(np.median(filtered, axis=0).astype(int))
    print(f"    [padrao] Calibracao OK: variancia {variance:.1f}, bbox {result_bbox} "
          f"({len(filtered)} deteccoes)")
    return result_bbox


def _calibrate_consistency(
    detections: list,
    max_dist: float = CALIBRATION_CONSISTENCY_MAX_DIST,
    min_consistent: int = CALIBRATION_MIN_CONSISTENT,
    max_variance: float = CALIBRATION_CONSISTENCY_VARIANCE,
) -> Optional[Tuple[int, int, int, int]]:
    """Calibracao por consistencia: aceita cluster de deteccoes espacialmente proximas."""
    bboxes = np.array(detections)
    clusters = _find_consistent_clusters(bboxes, max_dist)

    print(f"    [consistencia] {len(detections)} deteccoes -> {len(clusters)} cluster(s)")

    best_cluster_bbox = None
    best_cluster_score = (-1, 0.0)

    for idx, cluster_indices in enumerate(clusters):
        cluster_bboxes = bboxes[cluster_indices]
        size = len(cluster_indices)

        if size < min_consistent:
            print(f"    [consistencia] Cluster {idx}: {size} deteccoes "
                  f"(abaixo do minimo {min_consistent})")
            continue

        variance = cluster_bboxes.std(axis=0).max()
        median_bbox = np.median(cluster_bboxes, axis=0)

        print(f"    [consistencia] Cluster {idx}: {size} deteccoes, "
              f"variancia {variance:.1f}px, mediana {tuple(median_bbox.astype(int))}")

        if variance > max_variance:
            print(f"    [consistencia] Cluster {idx}: variancia {variance:.1f} > "
                  f"{max_variance}, rejeitado")
            continue

        score = (size, -variance)
        if score > best_cluster_score:
            best_cluster_score = score
            best_cluster_bbox = tuple(median_bbox.astype(int))

    if best_cluster_bbox is not None:
        print(f"    [consistencia] Calibracao OK: bbox {best_cluster_bbox}")
        return best_cluster_bbox

    print(f"    [consistencia] Nenhum cluster consistente encontrado")
    return None


def calibrate_bed(
    camera: CameraBase,
    bed_detector: BedDetector,
    display: DisplayManager,
    num_frames: int = CALIBRATION_FRAMES,
    max_variance: float = CALIBRATION_MAX_VARIANCE,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Calibra posição da cama por múltiplos frames.

    Args:
        camera: Instancia de camera (multiplataforma).
        bed_detector: Detector de cama.
        display: Gerenciador de display.
        num_frames: Número de frames para calibração.
        max_variance: Variação máxima permitida em pixels.

    Returns:
        Tuple (x1, y1, x2, y2) com bbox médio se estável, None se instável.
    """
    detections = []

    for i in range(num_frames):
        try:
            ret, frame = camera.read()
            if not ret or frame is None:
                continue

            # Aplica flip horizontal se configurado
            if FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            # Frame cru para ASETO (antes da normalização IR)
            raw_frame = frame.copy()

            # Normaliza frame para cameras IR (usado pelo COCO)
            frame = normalize_frame_for_ir(frame)

            bbox = bed_detector.detect_bed(frame, raw_frame=raw_frame, diagnostic=True)

            if bbox:
                detections.append(bbox)

            # Exibe frame com progresso
            progress_text = f"Frame {i + 1}/{num_frames}"
            frame = display.draw_calibration_progress(frame, progress_text, i + 1, num_frames)
            key = display.render(frame)

            # Permite sair durante calibração
            if key == ord("q") or key == ord("Q"):
                return None

            # Heartbeat durante calibracao
            send_heartbeat()

            time.sleep(FRAME_DELAY_SECONDS)

        except Exception as e:
            log_exception("Erro durante calibracao", e)
            continue

    # --- Logica de aceitacao dual ---
    min_detections = int(num_frames * CALIBRATION_MIN_DETECTION_RATE)

    # Caminho A: calibracao padrao (requer min_detections, filtra via IQR)
    if len(detections) >= min_detections:
        print(f"    {len(detections)}/{num_frames} deteccoes - tentando calibracao padrao")
        result = _calibrate_standard(detections, num_frames, min_detections, max_variance)
        if result is not None:
            return result

    # Caminho B: fallback por consistencia espacial
    if len(detections) >= CALIBRATION_MIN_CONSISTENT:
        print(f"    {len(detections)}/{num_frames} deteccoes - tentando calibracao por consistencia")
        result = _calibrate_consistency(detections)
        if result is not None:
            return result

    # Ambos falharam
    print(f"    Calibracao falhou: {len(detections)}/{num_frames} deteccoes "
          f"(minimo padrao={min_detections}, minimo consistencia={CALIBRATION_MIN_CONSISTENT})")
    print(f"    Dica: verifique os logs de diagnostico acima para ver o que o YOLO detectou")
    return None


def _filter_overlapping_boxes(boxes_xyxy: np.ndarray, iou_threshold: float = 0.4) -> list:
    """Filtra bboxes sobrepostas mantendo a de maior area (evita contar mesma pessoa 2x)."""
    if len(boxes_xyxy) <= 1:
        return list(range(len(boxes_xyxy)))

    areas = (boxes_xyxy[:, 2] - boxes_xyxy[:, 0]) * (boxes_xyxy[:, 3] - boxes_xyxy[:, 1])
    order = areas.argsort()[::-1]
    keep = []

    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes_xyxy[i, 0], boxes_xyxy[rest, 0])
        yy1 = np.maximum(boxes_xyxy[i, 1], boxes_xyxy[rest, 1])
        xx2 = np.minimum(boxes_xyxy[i, 2], boxes_xyxy[rest, 2])
        yy2 = np.minimum(boxes_xyxy[i, 3], boxes_xyxy[rest, 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[rest] - inter)
        order = rest[iou < iou_threshold]

    return keep


def validate_model_file(model_path: str) -> None:
    """
    Valida o arquivo de modelo .pt ANTES de entrega-lo ao ultralytics.

    Em ambiente offline, um .pt ausente/invalido (ex: ponteiro Git LFS de
    ~130 bytes apos clone sem git-lfs) faria o ultralytics tentar baixar da
    internet e falhar de forma obscura. Aqui falhamos rapido e com mensagem
    inequivoca.

    Raises:
        RuntimeError: Se o arquivo nao existe, e ponteiro LFS ou nao e um
            checkpoint valido.
    """
    p = Path(model_path)
    if not p.exists():
        raise RuntimeError(
            f"Modelo nao encontrado: {model_path}. "
            f"Sistema offline NAO baixa modelos - copie o arquivo manualmente."
        )

    with open(p, "rb") as f:
        head = f.read(256)

    if head.startswith(b"version https://git-lfs"):
        raise RuntimeError(
            f"Modelo {model_path} e um PONTEIRO Git LFS, nao o arquivo real. "
            f"Execute 'git lfs pull' com internet ou copie o .pt manualmente."
        )

    # Checkpoints torch sao arquivos zip (magic PK) ou pickle legado (\x80)
    if not (head.startswith(b"PK") or head.startswith(b"\x80")):
        raise RuntimeError(
            f"Modelo {model_path} nao parece um checkpoint valido "
            f"(cabecalho inesperado). Arquivo corrompido?"
        )

    size_mb = p.stat().st_size / (1024 * 1024)
    if size_mb < 1.0:
        raise RuntimeError(
            f"Modelo {model_path} tem apenas {size_mb:.2f} MB - arquivo truncado?"
        )

    print(f"    Modelo {model_path} validado ({size_mb:.1f} MB)")


def _select_patient_index(
    boxes_xyxy: np.ndarray,
    keep: list,
    bed_bbox: Tuple[int, int, int, int],
    last_centroid: Optional[Tuple[float, float]],
    frame_shape: Tuple[int, ...],
) -> Optional[int]:
    """
    Seleciona qual das deteccoes mantidas e a pessoa-paciente.

    Associacao leve (sem tracker): pontua cada bbox pela fracao contida na
    cama, proximidade do centro da cama e continuidade com o centroide do
    frame anterior. Retorna None quando nenhuma deteccao tem associacao
    minima com a cama (ex: apenas passantes/acompanhantes em pe) — a FSM
    trata como ausencia de evidencia, o que preserva alertas ativos.
    """
    bx1, by1, bx2, by2 = bed_bbox
    bed_cx = (bx1 + bx2) / 2.0
    bed_cy = (by1 + by2) / 2.0
    frame_diag = float(np.hypot(frame_shape[1], frame_shape[0]))

    best_idx = None
    best_score = -1.0
    best_containment = 0.0

    for i in keep:
        x1, y1, x2, y2 = boxes_xyxy[i]
        area = max(1.0, (x2 - x1) * (y2 - y1))

        ix1, iy1 = max(x1, bx1), max(y1, by1)
        ix2, iy2 = min(x2, bx2), min(y2, by2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        containment = inter / area

        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        dist_bed = float(np.hypot(cx - bed_cx, cy - bed_cy)) / frame_diag

        score = containment - 0.5 * dist_bed

        # Bonus de continuidade: mesma pessoa do frame anterior
        if last_centroid is not None:
            jump = float(np.hypot(cx - last_centroid[0], cy - last_centroid[1])) / frame_diag
            if jump <= PATIENT_ASSOC_MAX_JUMP_RATIO:
                score += 0.3 * (1.0 - jump / PATIENT_ASSOC_MAX_JUMP_RATIO)

        if score > best_score:
            best_score = score
            best_idx = i
            best_containment = containment

    # Sem associacao minima com a cama, nao ha paciente identificavel
    if best_idx is not None and best_containment < 0.15:
        return None

    return best_idx


def _kill_previous_camera_processes() -> None:
    """
    Mata instancias anteriores de main.py que possam estar segurando a camera.
    Roda ANTES de qualquer inicializacao de camera.
    """
    import subprocess
    my_pid = os.getpid()
    killed = 0
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*main.py"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                pid = int(line)
            except ValueError:
                continue
            if pid == my_pid:
                continue
            print(f"[Startup] Matando instancia anterior (PID {pid})...")
            try:
                subprocess.run(["kill", "-9", str(pid)], timeout=5)
                killed += 1
            except Exception:
                pass
    except Exception:
        pass

    if killed > 0:
        import time
        print(f"[Startup] {killed} processo(s) encerrado(s), aguardando liberacao da camera...")
        time.sleep(3)
    else:
        print("[Startup] Nenhuma instancia anterior encontrada")


def initialize_system() -> Tuple[CameraBase, YOLO, BedDetector, DisplayManager, AlertLogger, GPIOAlertManager]:
    """
    Inicializa todos os componentes do sistema.

    Returns:
        Tuple com (camera, yolo_pose, bed_detector, display, alert_logger, gpio_manager)

    Raises:
        Exception: Se falhar ao inicializar algum componente
    """
    # No Linux, aguarda X11 estar pronto (serviço pode iniciar antes do desktop)
    # IMPORTANTE: espera em fatias curtas COM heartbeat — uma espera bloqueante
    # maior que WatchdogSec derrubaria o servico em loop no boot sem monitor
    if IS_LINUX:
        display_available = False
        display_wait_slice = 5
        waited = 0
        while waited < DISPLAY_WAIT_TIMEOUT:
            send_heartbeat()
            if wait_for_display(timeout_seconds=display_wait_slice, check_interval=display_wait_slice):
                display_available = True
                break
            waited += display_wait_slice
        send_heartbeat()
        if display_available:
            logger.info("Display X11 disponível - modo GUI ativo")
        else:
            logger.warning("Display X11 não disponível - sistema rodará em modo headless")

    # Carrega identificacao do ambiente
    environment_id = get_environment_id()
    platform_info = get_platform_info()

    print("=" * 50)
    print("Sistema de Monitoramento de Quedas Hospitalares")
    print(f"Ambiente: {environment_id}")
    print(f"Plataforma: {platform_info['system']}")
    print("=" * 50)

    # 0. No Linux, libera camera de processos anteriores
    if IS_LINUX:
        _kill_previous_camera_processes()

    # 1. Inicialização da câmera
    print("\n[1/4] Inicializando camera...")
    camera = create_camera(CAMERA_INDEX, backend=CAMERA_BACKEND)

    if not camera.open():
        raise RuntimeError("Nao foi possivel abrir a camera")

    camera.set_resolution(640, 480)
    width, height = camera.get_resolution()

    print(f"    Camera inicializada com sucesso")
    print(f"    Resolucao: {width}x{height}")

    # 2. Valida e carrega modelo de pose (unico residente em memoria)
    # O modelo de cama (yolov8l, 87 MB) e carregado SOB DEMANDA apenas na
    # calibracao/recheck e liberado em seguida — evita OOM-kill no RPi.
    # O ASETO foi removido do pipeline (COCO histEq/raw assumiu a calibracao).
    print("\n[2/4] Validando e carregando modelo de pose...")
    validate_model_file(YOLO_POSE_MODEL)
    send_heartbeat()
    yolo_pose = YOLO(YOLO_POSE_MODEL)
    send_heartbeat()
    print(f"    Modelo {YOLO_POSE_MODEL} carregado (pose)")

    # 3. Inicializa modulos
    print("\n[3/4] Inicializando modulos...")
    bed_detector = BedDetector()
    display = DisplayManager(WINDOW_NAME)
    alert_logger = AlertLogger()

    print("    Modulos inicializados")
    if DEV_MODE:
        print("    Modo desenvolvimento ATIVO - imagens de alerta serao salvas")
    if DEV_SKIP_BED_DETECTION:
        print("    Modo DEV_SKIP_BED_DETECTION ATIVO - deteccao de cama ignorada")
    if FLIP_HORIZONTAL:
        print("    Flip horizontal ATIVO")

    # Inicializa gerenciador GPIO
    gpio_manager = GPIOAlertManager()

    return camera, yolo_pose, bed_detector, display, alert_logger, gpio_manager


def run_monitoring_loop(
    camera: CameraBase,
    yolo_pose: YOLO,
    bed_detector: BedDetector,
    display: DisplayManager,
    alert_logger: AlertLogger,
    bed_bbox: Tuple[int, int, int, int],
    gpio_manager: GPIOAlertManager,
) -> bool:
    """
    Executa o loop principal de monitoramento.

    Args:
        camera: Camera inicializada
        yolo_pose: Modelo YOLO para deteccao de pose
        bed_detector: Detector de cama
        display: Gerenciador de display
        alert_logger: Logger de alertas
        bed_bbox: Bounding box da cama calibrada
        gpio_manager: Gerenciador de alertas GPIO

    Returns:
        True se encerrou normalmente (usuario pediu), False se erro
    """
    # Inicializa analisador de pose e maquina de estados EMA
    pose_analyzer = PoseAnalyzer(
        bed_bbox=bed_bbox,
        confidence_high=POSE_CONFIDENCE_HIGH,
        confidence_min=POSE_CONFIDENCE_MIN,
        frames_to_confirm=POSE_FRAMES_TO_CONFIRM,
        frames_patient_detected=POSE_FRAMES_PATIENT_DETECTED,
    )
    pose_fsm = PoseStateMachineEMA()

    # Monitor para re-check da cama
    monitor = PatientMonitor(bed_bbox)

    print("\n" + "=" * 50)
    print("Sistema em monitoramento (YOLOv8-Pose)")
    print("Pressione Q para sair, R para reset")
    print("=" * 50 + "\n")

    # Variaveis de controle
    body_points: Optional[BodyPoints] = None
    analysis: Optional[PositionAnalysis] = None
    previous_pose_state: str = PoseStateMachineEMA.AGUARDANDO
    alert_feedback_until = 0
    last_alert_image = ""
    last_patient_centroid: Optional[Tuple[float, float]] = None
    last_person_count = 0

    # Controle de heartbeat
    last_heartbeat = time.time()

    # Controle de erros consecutivos (separados por tipo)
    consecutive_capture_errors = 0
    consecutive_processing_errors = 0

    # Log inicio do monitoramento
    alert_logger.log_info("Sistema de monitoramento iniciado")

    # Loop Principal de Monitoramento
    while True:
        try:
            frame_start = time.time()

            # Envia heartbeat periodicamente (watchdog + status para o painel)
            if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                send_heartbeat()
                write_status_file(pose_fsm.current_state, last_person_count)
                last_heartbeat = time.time()

            ret, frame = camera.read()
            if not ret or frame is None:
                consecutive_capture_errors += 1
                if consecutive_capture_errors <= 5 or consecutive_capture_errors % 10 == 0:
                    logger.warning(f"Falha ao capturar frame ({consecutive_capture_errors}/{MAX_CONSECUTIVE_ERRORS})")

                if consecutive_capture_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error("Muitos erros consecutivos de captura - tentando reiniciar sistema")
                    return False

                time.sleep(ERROR_RECOVERY_DELAY)
                continue

            # Reset contadores em captura bem-sucedida
            consecutive_capture_errors = 0

            # Aplica flip horizontal se configurado
            if FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            # Frame cru para ASETO (antes da normalização IR)
            raw_frame = frame.copy()

            # Normaliza frame para cameras IR (remove distorcao de cor)
            frame = normalize_frame_for_ir(frame)

            # Re-check da cama se necessario (ignorado em modo DEV_SKIP_BED_DETECTION)
            if not DEV_SKIP_BED_DETECTION and bed_detector.needs_recheck():
                # Evento raro (a cada horas): carrega o modelo de cama, roda e
                # libera. Heartbeat antes/depois pois o stall e de varios segundos
                send_heartbeat()
                validate_model_file(YOLO_BED_MODEL)
                bed_detector.ensure_model_loaded(YOLO_BED_MODEL)
                result = bed_detector.detect_bed_detailed(frame, raw_frame=raw_frame)
                bed_detector.release_model()
                send_heartbeat()
                if result is not None:
                    new_bbox, class_name, confidence, score = result
                    current_score = bed_detector.detected_score
                    if (bed_detector.is_bbox_consistent(new_bbox) and
                            score >= current_score):
                        bed_detector._accept_detection(new_bbox, class_name, confidence, score)
                        bed_bbox = new_bbox
                        bed_detector.save_reference(bed_bbox)
                        pose_analyzer.update_bed_bbox(bed_bbox)
                        monitor.update_bed_bbox(bed_bbox)
                        logger.info(f"Cama re-detectada: {bed_bbox} (score={score:.3f})")
                    else:
                        bed_detector.postpone_recheck()
                        if not bed_detector.is_bbox_consistent(new_bbox):
                            logger.info(f"Recheck ignorado: bbox inconsistente (IoU baixo)")
                        else:
                            logger.info(f"Recheck ignorado: score inferior ({score:.3f} < {current_score:.3f})")
                else:
                    bed_detector.postpone_recheck()

            # Detecta pose com YOLOv8-Pose (parametros de NMS explicitos —
            # defaults do Ultralytics ja mudaram entre versoes)
            results = yolo_pose.predict(
                frame,
                conf=YOLO_POSE_CONFIDENCE,
                iou=YOLO_POSE_IOU,
                imgsz=YOLO_POSE_IMGSZ,
                max_det=YOLO_POSE_MAX_DET,
                classes=[0],
                verbose=False,
            )

            body_points = None
            analysis = None
            person_count = 0
            person_bbox = None

            # Verifica se detectou pessoa com keypoints
            if len(results) > 0 and results[0].keypoints is not None:
                keypoints_data = results[0].keypoints
                boxes = results[0].boxes

                if keypoints_data.xy is not None and len(keypoints_data.xy) > 0:
                    # Filtra deteccoes duplicadas (bboxes sobrepostas da mesma pessoa)
                    raw_count = len(keypoints_data.xy)
                    if raw_count > 1 and boxes is not None and len(boxes) >= raw_count:
                        boxes_xyxy = boxes.xyxy.cpu().numpy()[:raw_count]
                        keep = _filter_overlapping_boxes(boxes_xyxy, iou_threshold=0.4)
                    else:
                        boxes_xyxy = None
                        keep = list(range(raw_count))
                    person_count = len(keep)

                    # Seleciona a pessoa-paciente (indice REAL do resultado YOLO,
                    # nunca [0] fixo — keypoints e bbox devem vir da mesma deteccao)
                    patient_idx = None
                    if person_count == 1:
                        patient_idx = keep[0]
                    elif person_count > 1 and COMPANION_ANALYSIS_ENABLED and boxes_xyxy is not None:
                        # Com acompanhante presente, associa o paciente a cama
                        # por geometria e continua a analise de risco
                        patient_idx = _select_patient_index(
                            boxes_xyxy, keep, bed_bbox, last_patient_centroid, frame.shape
                        )

                    if patient_idx is not None:
                        keypoints = keypoints_data.xy[patient_idx].cpu().numpy()

                        if keypoints_data.conf is not None and len(keypoints_data.conf) > patient_idx:
                            confidences = keypoints_data.conf[patient_idx].cpu().numpy()
                        else:
                            confidences = np.ones(len(keypoints))

                        # Extrai bbox da MESMA deteccao dos keypoints
                        if boxes is not None and len(boxes) > patient_idx:
                            person_bbox = tuple(
                                boxes.xyxy[patient_idx].cpu().numpy().astype(int)
                            )

                        # Continuidade de identidade: salto de centroide grande
                        # indica troca de pessoa — zera EMA de confiancas para
                        # nao contaminar a nova pessoa com a anterior
                        if person_bbox is not None:
                            cx = (person_bbox[0] + person_bbox[2]) / 2.0
                            cy = (person_bbox[1] + person_bbox[3]) / 2.0
                            if last_patient_centroid is not None:
                                frame_diag = float(np.hypot(frame.shape[1], frame.shape[0]))
                                jump = float(np.hypot(
                                    cx - last_patient_centroid[0],
                                    cy - last_patient_centroid[1],
                                )) / frame_diag
                                if jump > PATIENT_ASSOC_MAX_JUMP_RATIO:
                                    pose_analyzer.reset_confidence_ema()
                            last_patient_centroid = (cx, cy)

                        confidences = pose_analyzer.smooth_confidences(confidences)
                        body_points = pose_analyzer.extract_body_points(keypoints, confidences)
                        analysis = pose_analyzer.analyze_position(body_points, person_bbox)

            # Atualiza maquina de estados de pose
            pose_state = pose_fsm.update(analysis, body_points, person_count)
            pose_state_enum = PatientPoseState(pose_state)

            # Atualiza monitor (fail-safe: nunca "Cama Vazia" com alerta ativo)
            monitor.update(
                person_count,
                pose_state=pose_fsm.current_state,
                occlusion_presumed=pose_fsm.occlusion_presumed,
            )
            last_person_count = person_count

            # --- Renderizacao ---
            frame = display.draw_bed_polygon(frame, bed_bbox)

            if body_points:
                frame = display.draw_keypoints(frame, body_points, pose_state_enum, bed_bbox)

            frame = display.draw_pose_state_message(frame, pose_state_enum)

            status = monitor.get_status()
            if pose_state_enum == PatientPoseState.ACOMPANHADO:
                status_text = f"STATUS: {status} | PESSOAS: {person_count} (acompanhado)"
            elif pose_state_enum == PatientPoseState.PACIENTE_FORA:
                status_text = f"STATUS: {status} | POSE: {pose_state_enum.value} - ALERTA CRITICO!"
            elif pose_state_enum == PatientPoseState.RISCO_POTENCIAL:
                status_text = f"STATUS: {status} | POSE: {pose_state_enum.value} - ATENCAO!"
            elif pose_state_enum == PatientPoseState.ALERTA_PERSISTENTE:
                status_text = f"STATUS: {status} | POSE: {pose_state_enum.value} - VERIFICAR PACIENTE!"
            else:
                status_text = f"STATUS: {status} | POSE: {pose_state_enum.value}"

            frame = display.draw_status(frame, status_text)
            frame = display.draw_pose_dashboard(frame, body_points, pose_state_enum, analysis)

            ema_scores = pose_fsm.get_scores()
            frame = display.draw_ema_scores(frame, ema_scores)

            # Detecta mudanca de estado e loga alertas
            if pose_state != previous_pose_state:
                image_path = alert_logger.log_state_change(
                    previous_state=previous_pose_state,
                    new_state=pose_state,
                    frame=frame,  # Frame ja tem anotacoes
                )
                if image_path:
                    last_alert_image = image_path
                    alert_feedback_until = time.time() + 3.0
                    print(f"[ALERTA] {pose_state} - Imagem salva: {image_path}")
                elif pose_state in PoseStateMachineEMA.ALERT_STATES:
                    print(f"[ALERTA] {pose_state}")

                previous_pose_state = pose_state

            # Controle de alerta GPIO: usa o estado BRUTO da FSM (sem dwell de
            # publicacao) para acionar o alerta fisico o mais cedo possivel
            if pose_fsm.current_state in PoseStateMachineEMA.ALERT_STATES:
                gpio_manager.start_risk_alert()
            else:
                gpio_manager.stop_risk_alert()

            # Feedback visual de alerta salvo
            if time.time() < alert_feedback_until and last_alert_image:
                frame = display.draw_log_feedback(
                    frame,
                    f"Alerta #{alert_logger.get_alert_count()}",
                    alert_logger.get_image_count(),
                )

            # Renderiza frame no display
            key = display.render(frame)

            # Captura de teclas
            if key == ord("q") or key == ord("Q"):
                return True  # Encerramento normal

            if key == ord("r") or key == ord("R"):
                pose_fsm.reset()
                pose_analyzer.reset_confidence_ema()
                last_patient_centroid = None
                logger.info("Maquina de estados resetada")

            # Frame processado com sucesso — reset contador de erros de processamento
            consecutive_processing_errors = 0

            # Sleep adaptativo: só dorme o necessário para atingir o ciclo alvo
            elapsed = time.time() - frame_start
            remaining = FRAME_DELAY_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)

        except KeyboardInterrupt:
            logger.info("Interrompido pelo usuario (Ctrl+C)")
            return True

        except Exception as e:
            consecutive_processing_errors += 1
            log_exception(f"Erro de processamento ({consecutive_processing_errors}/{MAX_CONSECUTIVE_ERRORS})", e)

            if consecutive_processing_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.error("Muitos erros de processamento consecutivos - reiniciando sistema")
                return False

            time.sleep(ERROR_RECOVERY_DELAY)


def main():
    """
    Funcao principal com tratamento de erros e reinicializacao automatica.
    """
    camera = None
    display = None
    alert_logger = None
    gpio_manager = None

    init_attempts = 0

    while True:
        try:
            # Envia heartbeat no inicio
            send_heartbeat()
            write_status_file("INICIALIZANDO")

            # Inicializacao com retry
            init_attempts += 1
            logger.info(f"Tentativa de inicializacao {init_attempts}/{MAX_INIT_RETRIES}")

            camera, yolo_pose, bed_detector, display, alert_logger, gpio_manager = initialize_system()

            # Notifica systemd que o processo está vivo (calibração é fase operacional)
            _notify_systemd(b"READY=1")

            # Reset contador apos sucesso
            init_attempts = 0

            # Calibracao da cama
            print("\n[4/4] Calibrando sistema...")
            bed_bbox = None

            # Modo desenvolvimento: tenta usar referência salva primeiro
            if DEV_SKIP_BED_DETECTION:
                print("    [DEV] Modo desenvolvimento ativo - buscando referencia salva")
                saved_bbox = bed_detector.load_reference()
                if saved_bbox:
                    bed_bbox = saved_bbox
                    print(f"    [DEV] Usando referencia salva: {bed_bbox}")
                else:
                    print("    [DEV] AVISO: Nenhuma referencia salva encontrada")
                    print("    [DEV] Iniciando calibracao automatica...")
                    # Continua para calibracao normal em vez de sair

            calibration_attempts = 0
            max_calibration_attempts = 3
            calibration_start_time = time.time()
            calibration_timeout = 300  # 5 minutos maximo para calibracao
            while bed_bbox is None:
                send_heartbeat()

                # Modelo de cama e carregado apenas aqui (lazy) e liberado apos
                # a calibracao — nao pode ficar residente junto do pose no RPi
                if bed_detector.model is None:
                    validate_model_file(YOLO_BED_MODEL)
                    bed_detector.ensure_model_loaded(YOLO_BED_MODEL)
                    send_heartbeat()

                calibration_attempts += 1
                elapsed = time.time() - calibration_start_time
                print(f"    Calibracao automatica (tentativa {calibration_attempts}, {elapsed:.0f}s)...")
                bed_bbox = calibrate_bed(camera, bed_detector, display)

                if bed_bbox:
                    bed_detector.save_reference(bed_bbox)
                elif calibration_attempts >= max_calibration_attempts:
                    saved_bbox = bed_detector.load_reference()
                    if saved_bbox:
                        bed_bbox = saved_bbox
                        logger.warning(f"Calibracao falhou {max_calibration_attempts}x - usando referencia salva: {bed_bbox}")
                        print(f"    Usando referencia salva apos {max_calibration_attempts} falhas: {bed_bbox}")
                    elif elapsed >= calibration_timeout:
                        logger.error(f"Calibracao timeout ({calibration_timeout}s) sem referencia salva - reiniciando sistema")
                        raise RuntimeError("Calibracao timeout sem referencia de cama")
                    else:
                        logger.warning("Calibracao falhou e nao ha referencia salva - continuando tentativas...")
                        calibration_attempts = 0
                else:
                    ret, frame = camera.read()
                    if ret and frame is not None:
                        if FLIP_HORIZONTAL:
                            frame = cv2.flip(frame, 1)
                        frame = normalize_frame_for_ir(frame)
                        frame = display.draw_system_message(
                            frame,
                            "CALIBRACAO FALHOU",
                            f"Tentativa {calibration_attempts}/{max_calibration_attempts}...",
                            color=(0, 0, 255),
                        )
                        display.render(frame)

                    time.sleep(BED_STANDBY_RETRY_SECONDS)

            # Libera modelo de cama da memoria (recarregado no proximo recheck)
            bed_detector.release_model()

            # Exibe mensagem de sucesso
            config_complete_time = time.time()
            while time.time() - config_complete_time < CALIBRATION_SUCCESS_DISPLAY_SECONDS:
                ret, frame = camera.read()
                if ret and frame is not None:
                    if FLIP_HORIZONTAL:
                        frame = cv2.flip(frame, 1)
                    frame = normalize_frame_for_ir(frame)
                    frame = display.draw_bed_polygon(frame, bed_bbox)
                    frame = display.draw_system_message(
                        frame,
                        "CONFIGURACAO CONCLUIDA",
                        "Iniciando monitoramento...",
                        color=(0, 255, 0),
                    )
                    key = display.render(frame)

                    if key == ord("q") or key == ord("Q"):
                        logger.info("Encerrado pelo usuario durante inicializacao")
                        safe_cleanup(camera, display, gpio_manager)
                        return

                time.sleep(FRAME_DELAY_SECONDS)

            # Ativa indicador de sistema pronto (GPIO)
            gpio_manager.set_system_ready(True)

            # Loop de monitoramento
            user_requested_exit = run_monitoring_loop(
                camera, yolo_pose, bed_detector, display, alert_logger, bed_bbox, gpio_manager
            )

            # Cleanup
            if alert_logger:
                alert_logger.log_info("Sistema de monitoramento encerrado")
                print(f"\nTotal de alertas registrados: {alert_logger.get_alert_count()}")
                if DEV_MODE:
                    print(f"Imagens de alerta salvas: {alert_logger.get_image_count()}")

            safe_cleanup(camera, display, gpio_manager)
            camera = None
            display = None
            gpio_manager = None

            if user_requested_exit:
                logger.info("Encerramento normal solicitado pelo usuario")
                print("\n[SISTEMA] Encerramento solicitado pelo usuario")
                break
            else:
                # Erro no loop - tenta reiniciar
                logger.warning("Reiniciando sistema apos erro...")
                print("\n[SISTEMA] Reiniciando sistema apos erros de captura...")
                time.sleep(ERROR_RECOVERY_DELAY)

        except KeyboardInterrupt:
            logger.info("Interrompido pelo usuario (Ctrl+C)")
            break

        except Exception as e:
            log_exception("Erro fatal na inicializacao", e)
            safe_cleanup(camera, display, gpio_manager)
            camera = None
            display = None
            gpio_manager = None

            # Continua tentando indefinidamente
            # O watchdog de hardware reiniciará o sistema se necessário
            if init_attempts >= MAX_INIT_RETRIES:
                logger.warning(f"Ja foram {init_attempts} tentativas - continuando...")
                # Envia heartbeat para evitar reinicio do watchdog
                send_heartbeat()

            logger.info(f"Aguardando {INIT_RETRY_DELAY}s antes de tentar novamente...")
            time.sleep(INIT_RETRY_DELAY)

    # Cleanup final
    safe_cleanup(camera, display, gpio_manager)
    print("\nMonitoramento de pose encerrado.")


if __name__ == "__main__":
    main()
