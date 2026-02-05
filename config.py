"""
Configurações globais do Sistema de Monitoramento de Quedas Hospitalares.
"""

# Intervalo para re-verificação da cama (em horas)
BED_RECHECK_INTERVAL_HOURS = 6

# Intervalo de retry quando cama não é localizada (em segundos)
BED_STANDBY_RETRY_SECONDS = 2

# Tamanho da janela deslizante para buffer de features (em frames)
FEATURE_BUFFER_SIZE = 15

# Modelo YOLOv8 a utilizar (yolov8n.pt para melhor performance)
YOLO_MODEL = "yolov8n.pt"

# Modelo YOLOv8-Pose para detecção de keypoints
YOLO_POSE_MODEL = "yolov8n-pose.pt"

# Thresholds de confiança para keypoints
POSE_CONFIDENCE_HIGH = 0.7        # Confiança alta (ponto confiável)
POSE_CONFIDENCE_MIN = 0.3         # Confiança mínima (ignorar abaixo disso)

# Frames para confirmação de estado (legado - mantido para compatibilidade)
POSE_FRAMES_TO_CONFIRM = 10       # Frames consecutivos para mudar estado
POSE_FRAMES_PATIENT_DETECTED = 15 # Frames para confirmar paciente na cama

# Configurações EMA (Média Móvel Exponencial) para detecção de estados
EMA_ALPHA = 0.3                   # Fator de suavização (0.1=lento, 0.5=rápido)
EMA_THRESHOLD_ENTER_RISK = 0.5    # Score para entrar em RISCO_POTENCIAL
EMA_THRESHOLD_EXIT_RISK = 0.3     # Score para sair de RISCO_POTENCIAL
EMA_THRESHOLD_ENTER_OUT = 0.45    # Score para entrar em PACIENTE_FORA (2 frames)
EMA_THRESHOLD_EXIT_OUT = 0.3      # Score para sair de PACIENTE_FORA
EMA_THRESHOLD_PATIENT_DETECTED = 0.8  # Score para confirmar paciente na cama
EMA_THRESHOLD_PATIENT_LOST = 0.15     # Score para considerar paciente perdido (muito baixo)

# Índices dos keypoints COCO format (YOLOv8-Pose)
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_HIP = 11
KP_RIGHT_HIP = 12
KP_LEFT_KNEE = 13
KP_RIGHT_KNEE = 14
KP_LEFT_ANKLE = 15
KP_RIGHT_ANKLE = 16

# Índice da câmera (0 = câmera padrão)
CAMERA_INDEX = 0

# Classes YOLO COCO para detecção
YOLO_CLASS_PERSON = 0

# Nomes das classes COCO para detectar cama (resolução dinâmica por nome)
BED_CLASS_NAMES = ["bed", "couch"]

# Thresholds para transições de estado
THRESHOLD_REL_HEIGHT_SITTING = 0.6  # Altura relativa indicando paciente sentando
THRESHOLD_DELTA_Y_ALERT = 5.0  # Velocidade vertical para estado de alerta
THRESHOLD_OUTSIDE_BED_MARGIN = 0.1  # Margem para considerar paciente fora da cama

# Calibração do sistema
CALIBRATION_FRAMES = 20              # Quadros para calibração (configurável)
CALIBRATION_MAX_VARIANCE = 15        # Variação máxima em pixels para considerar estável
CALIBRATION_SUCCESS_DISPLAY_SECONDS = 3  # Tempo para mostrar "Configuração concluída"
CALIBRATION_MIN_DETECTION_RATE = 0.8  # Mínimo 80% de detecções para calibração válida

# Controle de FPS
FRAME_DELAY_SECONDS = 0.2            # Sleep entre frames (5 FPS)

# Caminho para persistência de referência da cama
BED_REFERENCE_PATH = "data/bed_reference.json"

# Diretório para logs de eventos
LOGS_DIR = "data/logs"

# Configurações de visualização
WINDOW_NAME = "Monitor de Quedas Hospitalares"
DASHBOARD_WIDTH = 200  # Largura do painel lateral em pixels
FLIP_HORIZONTAL = True  # Inverter imagem horizontalmente (espelho)

# Modo de desenvolvimento/homologação
DEV_MODE = True  # Quando True, salva imagens de alertas para evidência

# Modo de desenvolvimento: ignora detecção de cama
# Quando True, usa a última referência salva em bed_reference.json
# Útil para testes em ambientes sem cama/sofá disponível
DEV_SKIP_BED_DETECTION = True

# Diretório para imagens de alertas (modo dev/homologação)
ALERT_IMAGES_DIR = "data/alert_images"
MAX_ALERT_IMAGES = 50  # Máximo de imagens retidas no diretório

# Arquivo de log de alertas (rotacionado por tempo)
ALERT_LOG_PATH = "data/logs/alerts.log"
ALERT_LOG_RETENTION_DAYS = 5  # Manter logs por 5 dias

# Identificação do ambiente (para deploy em múltiplos Raspberry Pi)
ENVIRONMENT_CONFIG_PATH = "config/environment.json"
ENVIRONMENT_DEFAULT_ID = "NAO-CONFIGURADO"

# =============================================================================
# Platform Configuration
# =============================================================================
# Modo GPIO (None = auto-detectar, True = forçar real, False = forçar simulado)
GPIO_REAL_MODE = None

# Tempo máximo para aguardar X11 estar disponível no boot (segundos)
# O serviço systemd pode iniciar antes do desktop estar pronto
# O sistema continua mesmo sem monitor físico conectado
DISPLAY_WAIT_TIMEOUT = 120

# =============================================================================
# GPIO Configuration (Raspberry Pi only)
# =============================================================================
GPIO_PIN_ALERT = 16          # Pino para alerta de risco (pisca)
GPIO_PIN_SYSTEM_READY = 20   # Pino para sistema configurado
GPIO_BLINK_INTERVAL = 0.5    # Intervalo de pisca em segundos
GPIO_ALERT_DURATION = 30     # Duracao maxima do alerta em segundos
