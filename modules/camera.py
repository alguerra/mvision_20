"""
Modulo de abstracao de camera para multiplataforma.

Detecta a plataforma (Windows/Linux) e usa o backend apropriado:
- Windows: OpenCV (cv2.VideoCapture + cv2.imshow)
- Linux/Raspberry Pi: Picamera2 + OpenCV para processamento
"""

import os
import platform
import sys
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np

# Detecta plataforma uma vez na importacao
PLATFORM = platform.system()
IS_WINDOWS = PLATFORM == "Windows"
IS_LINUX = PLATFORM == "Linux"


def is_raspberry_pi() -> bool:
    """
    Detecta se está rodando em Raspberry Pi.

    Usa múltiplos métodos para maior confiabilidade:
    1. Device tree (mais confiável para modelos recentes)
    2. /proc/cpuinfo (fallback para modelos mais antigos)

    Returns:
        True se estiver rodando em Raspberry Pi
    """
    if not IS_LINUX:
        return False

    # Método 1: Device tree (mais confiável para Pi 4, Pi 5, etc)
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as f:
            model = f.read().lower()
            if 'raspberry pi' in model:
                return True
    except (FileNotFoundError, PermissionError, IOError):
        pass

    # Método 2: /proc/cpuinfo (fallback)
    try:
        with open('/proc/cpuinfo', 'r') as f:
            content = f.read()
            if 'Raspberry' in content or 'BCM' in content:
                return True
    except (FileNotFoundError, PermissionError, IOError):
        pass

    return False


def has_display_available() -> bool:
    """
    Verifica se há display disponível no sistema.

    - Windows: sempre retorna True (assume que há display)
    - Linux: verifica variável DISPLAY

    Returns:
        True se há display disponível para GUI
    """
    if IS_WINDOWS:
        return True

    # No Linux, verifica variável DISPLAY
    display = os.environ.get('DISPLAY')
    return display is not None and display != ''


class CameraBase(ABC):
    """Interface abstrata para camera."""

    @abstractmethod
    def open(self) -> bool:
        """Abre a camera. Retorna True se sucesso."""
        pass

    @abstractmethod
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Captura um frame. Retorna (sucesso, frame)."""
        pass

    @abstractmethod
    def release(self) -> None:
        """Libera recursos da camera."""
        pass

    @abstractmethod
    def is_opened(self) -> bool:
        """Verifica se camera esta aberta."""
        pass

    @abstractmethod
    def set_resolution(self, width: int, height: int) -> None:
        """Define resolucao da camera."""
        pass

    @abstractmethod
    def get_resolution(self) -> Tuple[int, int]:
        """Retorna resolucao atual (width, height)."""
        pass


class CameraOpenCV(CameraBase):
    """Implementacao de camera usando OpenCV (Windows)."""

    def __init__(self, camera_index: int = 0):
        """
        Inicializa camera OpenCV.

        Args:
            camera_index: Indice da camera (0 = padrao)
        """
        import cv2
        self.cv2 = cv2
        self.camera_index = camera_index
        self.cap: Optional[cv2.VideoCapture] = None
        self.width = 640
        self.height = 480

    def open(self) -> bool:
        self.cap = self.cv2.VideoCapture(self.camera_index)
        if self.cap.isOpened():
            self.set_resolution(self.width, self.height)
            return True
        return False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None:
            return False, None
        return self.cap.read()

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def is_opened(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def set_resolution(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        if self.cap is not None:
            self.cap.set(self.cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(self.cv2.CAP_PROP_FRAME_HEIGHT, height)

    def get_resolution(self) -> Tuple[int, int]:
        if self.cap is not None:
            w = int(self.cap.get(self.cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.cap.get(self.cv2.CAP_PROP_FRAME_HEIGHT))
            return w, h
        return self.width, self.height


class CameraPicamera(CameraBase):
    """Implementacao de camera usando Picamera2 (Raspberry Pi)."""

    def __init__(self):
        """Inicializa camera Picamera2."""
        self.picam2 = None
        self.width = 640
        self.height = 480
        self._is_open = False

    def open(self) -> bool:
        try:
            from picamera2 import Picamera2

            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            self.picam2.configure(config)
            self.picam2.start()
            self._is_open = True
            return True
        except Exception as e:
            print(f"[Camera] Erro ao inicializar Picamera2: {e}")
            self._is_open = False
            return False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self._is_open or self.picam2 is None:
            return False, None
        try:
            # Picamera2 retorna RGB, OpenCV usa BGR
            import cv2
            frame = self.picam2.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return True, frame
        except Exception:
            return False, None

    def release(self) -> None:
        if self.picam2 is not None:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None
        self._is_open = False

    def is_opened(self) -> bool:
        return self._is_open

    def set_resolution(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        # Se ja estiver aberta, precisa reconfigurar
        if self._is_open and self.picam2 is not None:
            self.picam2.stop()
            config = self.picam2.create_preview_configuration(
                main={"size": (width, height), "format": "RGB888"}
            )
            self.picam2.configure(config)
            self.picam2.start()

    def get_resolution(self) -> Tuple[int, int]:
        return self.width, self.height


class DisplayBase(ABC):
    """Interface abstrata para display."""

    @abstractmethod
    def show(self, window_name: str, frame: np.ndarray) -> None:
        """Exibe frame na tela."""
        pass

    @abstractmethod
    def wait_key(self, delay: int = 1) -> int:
        """Aguarda tecla. Retorna codigo da tecla ou -1."""
        pass

    @abstractmethod
    def destroy_all(self) -> None:
        """Fecha todas as janelas."""
        pass


class DisplayOpenCV(DisplayBase):
    """Display usando OpenCV (Windows com GUI)."""

    def __init__(self):
        import cv2
        self.cv2 = cv2

    def show(self, window_name: str, frame: np.ndarray) -> None:
        self.cv2.imshow(window_name, frame)

    def wait_key(self, delay: int = 1) -> int:
        return self.cv2.waitKey(delay) & 0xFF

    def destroy_all(self) -> None:
        self.cv2.destroyAllWindows()


class DisplayHeadless(DisplayBase):
    """Display headless para Raspberry Pi sem monitor."""

    def __init__(self):
        self._last_key = -1

    def show(self, window_name: str, frame: np.ndarray) -> None:
        # Nao exibe nada - modo headless
        pass

    def wait_key(self, delay: int = 1) -> int:
        # Sem GUI, retorna -1 (nenhuma tecla)
        # Em producao, controle sera via sinais ou API
        import time
        time.sleep(delay / 1000.0)  # Simula delay do waitKey
        return -1

    def destroy_all(self) -> None:
        pass


def create_camera(camera_index: int = 0) -> CameraBase:
    """
    Cria instancia de camera apropriada para a plataforma.

    Args:
        camera_index: Indice da camera (usado apenas no Windows)

    Returns:
        Instancia de CameraBase
    """
    if IS_WINDOWS:
        print(f"[Camera] Plataforma Windows - usando OpenCV")
        return CameraOpenCV(camera_index)
    elif IS_LINUX:
        print(f"[Camera] Plataforma Linux - usando Picamera2")
        return CameraPicamera()
    else:
        print(f"[Camera] Plataforma {PLATFORM} - tentando OpenCV")
        return CameraOpenCV(camera_index)


def create_display(headless: bool = False) -> DisplayBase:
    """
    Cria instancia de display apropriada para a plataforma.

    A detecção é feita na seguinte ordem:
    1. Se headless=True foi passado explicitamente, usa modo headless
    2. Se DISPLAY_GUI_MODE está configurado em config.py, usa essa configuração
    3. Caso contrário, auto-detecta baseado na disponibilidade de display

    Args:
        headless: Se True, força display headless (sem GUI)

    Returns:
        Instancia de DisplayBase
    """
    from config import DISPLAY_GUI_MODE

    # Determina se deve usar GUI ou headless
    if headless:
        # Parâmetro explícito tem prioridade
        use_gui = False
        reason = "parametro headless=True"
    elif DISPLAY_GUI_MODE is not None:
        # Override manual via config.py
        use_gui = DISPLAY_GUI_MODE
        reason = f"config DISPLAY_GUI_MODE={DISPLAY_GUI_MODE}"
    else:
        # Auto-detecção
        use_gui = has_display_available()
        reason = f"auto-detectado (DISPLAY={'presente' if use_gui else 'ausente'})"

    if use_gui:
        print(f"[Display] Modo GUI ativado ({reason})")
        return DisplayOpenCV()
    else:
        print(f"[Display] Modo headless ativado ({reason})")
        return DisplayHeadless()


def get_platform_info() -> dict:
    """
    Retorna informacoes da plataforma.

    Returns:
        Dict com informacoes da plataforma
    """
    return {
        "system": PLATFORM,
        "is_windows": IS_WINDOWS,
        "is_linux": IS_LINUX,
        "is_raspberry_pi": is_raspberry_pi(),
        "has_display": has_display_available(),
        "python_version": sys.version,
    }
