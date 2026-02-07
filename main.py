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

from ultralytics import YOLO

from config import (
    BED_STANDBY_RETRY_SECONDS,
    CALIBRATION_FRAMES,
    CALIBRATION_MAX_VARIANCE,
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
    YOLO_MODEL,
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

def send_heartbeat() -> None:
    """
    Envia heartbeat para o watchdog do sistema.
    Atualiza o timestamp do arquivo de heartbeat.
    """
    if not IS_LINUX:
        return  # Watchdog apenas no Linux/Raspberry Pi

    try:
        Path(HEARTBEAT_FILE).touch()
    except Exception:
        pass  # Ignora erros de heartbeat


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

            bbox = bed_detector.detect_bed(frame)

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

    # Verifica se teve detecções suficientes
    min_detections = int(num_frames * CALIBRATION_MIN_DETECTION_RATE)
    if len(detections) < min_detections:
        print(f"    Calibracao falhou: apenas {len(detections)}/{num_frames} deteccoes")
        return None

    # Calcula variância
    bboxes = np.array(detections)
    variance = bboxes.std(axis=0).max()

    if variance > max_variance:
        print(f"    Calibracao falhou: variancia {variance:.1f} > {max_variance}")
        return None

    # Retorna média
    avg_bbox = tuple(bboxes.mean(axis=0).astype(int))
    print(f"    Calibracao OK: variancia {variance:.1f}, bbox medio {avg_bbox}")
    return avg_bbox


def initialize_system() -> Tuple[CameraBase, YOLO, YOLO, BedDetector, DisplayManager, AlertLogger, GPIOAlertManager]:
    """
    Inicializa todos os componentes do sistema.

    Returns:
        Tuple com (camera, yolo, yolo_pose, bed_detector, display, alert_logger, gpio_manager)

    Raises:
        Exception: Se falhar ao inicializar algum componente
    """
    # No Linux, aguarda X11 estar pronto (serviço pode iniciar antes do desktop)
    # Não falha se não houver monitor - apenas aguarda o X11 inicializar
    if IS_LINUX:
        wait_for_display(timeout_seconds=DISPLAY_WAIT_TIMEOUT, check_interval=5)
        # Continua mesmo se não encontrar display - o X11 virtual pode estar ativo

    # Carrega identificacao do ambiente
    environment_id = get_environment_id()
    platform_info = get_platform_info()

    print("=" * 50)
    print("Sistema de Monitoramento de Quedas Hospitalares")
    print(f"Ambiente: {environment_id}")
    print(f"Plataforma: {platform_info['system']}")
    print("=" * 50)

    # 1. Inicialização da câmera
    print("\n[1/4] Inicializando camera...")
    camera = create_camera(CAMERA_INDEX, backend=CAMERA_BACKEND)

    if not camera.open():
        raise RuntimeError("Nao foi possivel abrir a camera")

    camera.set_resolution(640, 480)
    width, height = camera.get_resolution()

    print(f"    Camera inicializada com sucesso")
    print(f"    Resolucao: {width}x{height}")

    # 2. Carrega modelos YOLO
    print("\n[2/4] Carregando modelos YOLO...")
    yolo = YOLO(YOLO_MODEL)
    print(f"    Modelo {YOLO_MODEL} carregado (deteccao de cama)")

    yolo_pose = YOLO(YOLO_POSE_MODEL)
    print(f"    Modelo {YOLO_POSE_MODEL} carregado (pose)")

    # 3. Inicializa modulos
    print("\n[3/4] Inicializando modulos...")
    bed_detector = BedDetector(yolo)
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

    return camera, yolo, yolo_pose, bed_detector, display, alert_logger, gpio_manager


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

    # Controle de heartbeat
    last_heartbeat = time.time()

    # Controle de erros consecutivos
    consecutive_errors = 0

    # Log inicio do monitoramento
    alert_logger.log_info("Sistema de monitoramento iniciado")

    # Loop Principal de Monitoramento
    while True:
        try:
            # Envia heartbeat periodicamente
            if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                send_heartbeat()
                last_heartbeat = time.time()

            ret, frame = camera.read()
            if not ret or frame is None:
                consecutive_errors += 1
                if consecutive_errors <= 5 or consecutive_errors % 10 == 0:
                    logger.warning(f"Falha ao capturar frame ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})")

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error("Muitos erros consecutivos de captura - tentando reiniciar sistema")
                    return False

                time.sleep(ERROR_RECOVERY_DELAY)
                continue

            # Reset contador de erros em sucesso
            consecutive_errors = 0

            # Aplica flip horizontal se configurado
            if FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            # Re-check da cama se necessario (ignorado em modo DEV_SKIP_BED_DETECTION)
            if not DEV_SKIP_BED_DETECTION and bed_detector.needs_recheck():
                new_bbox = bed_detector.detect_bed(frame)
                if new_bbox:
                    bed_bbox = new_bbox
                    bed_detector.save_reference(bed_bbox)
                    pose_analyzer.update_bed_bbox(bed_bbox)
                    monitor.update_bed_bbox(bed_bbox)
                    logger.info(f"Cama re-detectada: {bed_bbox}")

            # Detecta pose com YOLOv8-Pose
            results = yolo_pose.predict(frame, verbose=False)

            body_points = None
            analysis = None
            person_count = 0

            # Verifica se detectou pessoa com keypoints
            if len(results) > 0 and results[0].keypoints is not None:
                keypoints_data = results[0].keypoints

                if keypoints_data.xy is not None and len(keypoints_data.xy) > 0:
                    person_count = len(keypoints_data.xy)

                    if person_count == 1:
                        keypoints = keypoints_data.xy[0].cpu().numpy()

                        if keypoints_data.conf is not None and len(keypoints_data.conf) > 0:
                            confidences = keypoints_data.conf[0].cpu().numpy()
                        else:
                            confidences = np.ones(len(keypoints))

                        body_points = pose_analyzer.extract_body_points(keypoints, confidences)
                        analysis = pose_analyzer.analyze_position(body_points)

            # Atualiza maquina de estados de pose
            pose_state = pose_fsm.update(analysis, body_points, person_count)
            pose_state_enum = PatientPoseState(pose_state)

            # Atualiza monitor
            monitor.update(person_count)

            # --- Renderizacao ---
            frame = display.draw_bed_polygon(frame, bed_bbox)

            if body_points:
                frame = display.draw_keypoints(frame, body_points, pose_state_enum, bed_bbox)

            frame = display.draw_pose_state_message(frame, pose_state_enum)

            status = monitor.get_status()
            if person_count > 1:
                status_text = f"STATUS: {status} | PESSOAS: {person_count} (acompanhado)"
            elif pose_state_enum == PatientPoseState.PACIENTE_FORA:
                status_text = f"STATUS: {status} | POSE: {pose_state_enum.value} - ALERTA CRITICO!"
            elif pose_state_enum == PatientPoseState.RISCO_POTENCIAL:
                status_text = f"STATUS: {status} | POSE: {pose_state_enum.value} - ATENCAO!"
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
                elif pose_state in [PoseStateMachineEMA.RISCO_POTENCIAL, PoseStateMachineEMA.PACIENTE_FORA]:
                    print(f"[ALERTA] {pose_state}")

                # Controle de alerta GPIO
                if pose_state in [PoseStateMachineEMA.RISCO_POTENCIAL, PoseStateMachineEMA.PACIENTE_FORA]:
                    gpio_manager.start_risk_alert()
                elif pose_state == PoseStateMachineEMA.MONITORANDO:
                    # So para o alerta se paciente VOLTOU para a cama
                    # Se foi para AGUARDANDO (desapareceu), deixa o alerta completar o ciclo
                    gpio_manager.stop_risk_alert()

                previous_pose_state = pose_state

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
                logger.info("Maquina de estados resetada")

            time.sleep(FRAME_DELAY_SECONDS)

        except KeyboardInterrupt:
            logger.info("Interrompido pelo usuario (Ctrl+C)")
            return True

        except Exception as e:
            consecutive_errors += 1
            log_exception(f"Erro no loop principal ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})", e)

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.error("Muitos erros consecutivos - reiniciando sistema")
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

            # Inicializacao com retry
            init_attempts += 1
            logger.info(f"Tentativa de inicializacao {init_attempts}/{MAX_INIT_RETRIES}")

            camera, yolo, yolo_pose, bed_detector, display, alert_logger, gpio_manager = initialize_system()

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

            while bed_bbox is None:
                print("    Iniciando calibracao automatica...")
                bed_bbox = calibrate_bed(camera, bed_detector, display)

                if bed_bbox:
                    bed_detector.save_reference(bed_bbox)
                else:
                    # Mostra mensagem de falha
                    ret, frame = camera.read()
                    if ret and frame is not None:
                        if FLIP_HORIZONTAL:
                            frame = cv2.flip(frame, 1)
                        frame = display.draw_system_message(
                            frame,
                            "CALIBRACAO FALHOU",
                            "Tentando novamente em 2 segundos...",
                            color=(0, 0, 255),
                        )
                        display.render(frame)

                    send_heartbeat()
                    time.sleep(BED_STANDBY_RETRY_SECONDS)

            # Exibe mensagem de sucesso
            config_complete_time = time.time()
            while time.time() - config_complete_time < CALIBRATION_SUCCESS_DISPLAY_SECONDS:
                ret, frame = camera.read()
                if ret and frame is not None:
                    if FLIP_HORIZONTAL:
                        frame = cv2.flip(frame, 1)
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

            # Ativa indicador de sistema pronto
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
