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


def wait_for_display(timeout_seconds: int = 120, check_interval: int = 5) -> bool:
    """
    Aguarda até que o display (GUI) esteja disponível.

    Útil quando o serviço systemd inicia antes do X11/Wayland estar pronto.
    No Windows, retorna imediatamente.

    Args:
        timeout_seconds: Tempo máximo de espera em segundos (default: 120)
        check_interval: Intervalo entre verificações em segundos (default: 5)

    Returns:
        True se o display ficou disponível, False se timeout
    """
    import time

    if IS_WINDOWS:
        return True

    print(f"[Display] Aguardando GUI estar disponível (timeout: {timeout_seconds}s)...")

    elapsed = 0
    while elapsed < timeout_seconds:
        # Verifica variável DISPLAY
        if has_display_available():
            # Tenta verificar se o X11 está realmente funcional
            try:
                import subprocess
                result = subprocess.run(
                    ['xset', 'q'],
                    capture_output=True,
                    timeout=5,
                    env=os.environ
                )
                if result.returncode == 0:
                    print(f"[Display] GUI disponível após {elapsed}s")
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass

        time.sleep(check_interval)
        elapsed += check_interval
        if elapsed % 30 == 0:
            print(f"[Display] Ainda aguardando GUI... ({elapsed}s)")

    print(f"[Display] TIMEOUT: GUI não disponível após {timeout_seconds}s")
    return False


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

    def __init__(self, camera_index: int = 0, backend: Optional[str] = None):
        """
        Inicializa camera OpenCV.

        Args:
            camera_index: Indice da camera (0 = padrao)
            backend: Backend de captura ("DSHOW", "MSMF", None = auto)
        """
        import cv2
        self.cv2 = cv2
        self.camera_index = camera_index
        self.cap: Optional[cv2.VideoCapture] = None
        self.width = 640
        self.height = 480
        self._backend = self._resolve_backend(backend)
        self._backend_name = backend
        self._consecutive_errors = 0
        self._max_errors_before_restart = 5

    def _resolve_backend(self, backend: Optional[str]) -> int:
        """Converte string de backend para constante cv2.CAP_*."""
        if backend is None:
            return self.cv2.CAP_ANY
        backend_map = {
            "DSHOW": self.cv2.CAP_DSHOW,
            "MSMF": self.cv2.CAP_MSMF,
            "V4L2": self.cv2.CAP_V4L2,
        }
        resolved = backend_map.get(backend.upper())
        if resolved is None:
            print(f"[Camera] Backend '{backend}' desconhecido, usando auto")
            return self.cv2.CAP_ANY
        return resolved

    def open(self) -> bool:
        self.cap = self.cv2.VideoCapture(self.camera_index, self._backend)
        if self.cap.isOpened():
            self._configure_capture()
            self.set_resolution(self.width, self.height)
            try:
                backend_name = self.cap.getBackendName()
            except Exception:
                backend_name = self._backend_name or "desconhecido"
            print(f"[Camera] Aberta com backend: {backend_name}")
            return True
        return False

    def _configure_capture(self) -> None:
        """Configura propriedades de captura para evitar acumulo de buffer."""
        self.cap.set(self.cv2.CAP_PROP_BUFFERSIZE, 1)
        # Reduz FPS da camera para perto da taxa de leitura do sistema (~5 FPS)
        # Evita acumulo de frames no buffer interno do DirectShow
        self.cap.set(self.cv2.CAP_PROP_FPS, 10)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None:
            return False, None
        # Drena frames antigos do buffer para obter o mais recente
        self.cap.grab()
        ret, frame = self.cap.read()
        if ret:
            self._consecutive_errors = 0
            return True, frame
        self._consecutive_errors += 1
        if self._consecutive_errors <= 3:
            print(f"[Camera] Erro ao capturar frame ({self._consecutive_errors})")
        if self._consecutive_errors >= self._max_errors_before_restart:
            print("[Camera] Muitos erros consecutivos, tentando reiniciar...")
            self._restart_camera()
        return False, None

    def _restart_camera(self) -> None:
        """Tenta reiniciar a camera apos erros."""
        import time
        try:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            time.sleep(1)
            self.cap = self.cv2.VideoCapture(self.camera_index, self._backend)
            if self.cap.isOpened():
                self._configure_capture()
                self.set_resolution(self.width, self.height)
                self._consecutive_errors = 0
                print("[Camera] OpenCV reiniciada com sucesso")
            else:
                print("[Camera] Falha ao reiniciar - camera nao abriu")
        except Exception as e:
            print(f"[Camera] Falha ao reiniciar camera: {e}")

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
        self._consecutive_errors = 0
        self._max_errors_before_restart = 5

    def _cleanup_camera(self) -> None:
        """Libera recursos da camera para permitir re-inicializacao."""
        if self.picam2 is not None:
            try:
                self.picam2.stop()
            except Exception:
                pass
            try:
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None

    def open(self, max_retries: int = 3, retry_delay: float = 2.0) -> bool:
        import time
        from picamera2 import Picamera2

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[Camera] Inicializando Picamera2 (tentativa {attempt}/{max_retries})...")
                self._cleanup_camera()
                self.picam2 = Picamera2()
                config = self.picam2.create_preview_configuration(
                    main={"size": (self.width, self.height), "format": "RGB888"}
                )
                self.picam2.configure(config)
                self.picam2.start()
                self._is_open = True
                self._consecutive_errors = 0
                print("[Camera] Picamera2 inicializada com sucesso")
                return True
            except Exception as e:
                print(f"[Camera] Erro na tentativa {attempt}: {e}")
                self._cleanup_camera()
                if attempt < max_retries:
                    print(f"[Camera] Aguardando {retry_delay}s antes de tentar novamente...")
                    time.sleep(retry_delay)

        print("[Camera] Falha ao inicializar Picamera2 apos todas as tentativas")
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
            self._consecutive_errors = 0  # Reset em sucesso
            return True, frame
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                print(f"[Camera] Erro ao capturar frame: {e}")

            # Tenta reiniciar a camera se muitos erros
            if self._consecutive_errors >= self._max_errors_before_restart:
                print("[Camera] Muitos erros consecutivos, tentando reiniciar...")
                self._restart_camera()

            return False, None

    def _restart_camera(self) -> None:
        """Tenta reiniciar a camera apos erros."""
        try:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                except Exception:
                    pass
                try:
                    self.picam2.close()
                except Exception:
                    pass

            import time
            time.sleep(1)  # Aguarda antes de reiniciar

            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            self.picam2.configure(config)
            self.picam2.start()
            self._is_open = True
            self._consecutive_errors = 0
            print("[Camera] Picamera2 reiniciada com sucesso")
        except Exception as e:
            print(f"[Camera] Falha ao reiniciar camera: {e}")
            self._is_open = False

    def release(self) -> None:
        print("[Camera] Liberando recursos da Picamera2...")
        if self.picam2 is not None:
            try:
                self.picam2.stop()
                print("[Camera] Picamera2 parada")
            except Exception as e:
                print(f"[Camera] Erro ao parar: {e}")
            try:
                self.picam2.close()
                print("[Camera] Picamera2 fechada")
            except Exception as e:
                print(f"[Camera] Erro ao fechar: {e}")
            self.picam2 = None
        self._is_open = False

    def is_opened(self) -> bool:
        return self._is_open

    def set_resolution(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        # Se ja estiver aberta, precisa reconfigurar
        if self._is_open and self.picam2 is not None:
            print(f"[Camera] Alterando resolucao para {width}x{height}...")
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


def create_camera(camera_index: int = 0, backend: Optional[str] = None) -> CameraBase:
    """
    Cria instancia de camera apropriada para a plataforma.

    Args:
        camera_index: Indice da camera (usado apenas no Windows)
        backend: Backend OpenCV ("DSHOW", "MSMF", None = auto). Ignorado no Picamera2.

    Returns:
        Instancia de CameraBase
    """
    if IS_WINDOWS:
        print(f"[Camera] Plataforma Windows - usando OpenCV")
        return CameraOpenCV(camera_index, backend=backend)
    elif IS_LINUX:
        print(f"[Camera] Plataforma Linux - usando Picamera2")
        return CameraPicamera()
    else:
        print(f"[Camera] Plataforma {PLATFORM} - tentando OpenCV")
        return CameraOpenCV(camera_index, backend=backend)


def create_display(headless: bool = False) -> DisplayBase:
    """
    Cria instancia de display para exibição com OpenCV.

    O sistema aguarda a GUI estar disponível (via wait_for_display)
    antes de chamar esta função, então sempre usa modo GUI.

    Args:
        headless: Se True, força display headless (não recomendado)

    Returns:
        Instancia de DisplayBase
    """
    if headless:
        print("[Display] Modo headless (sem GUI)")
        return DisplayHeadless()

    print("[Display] Modo GUI com OpenCV")
    return DisplayOpenCV()


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
