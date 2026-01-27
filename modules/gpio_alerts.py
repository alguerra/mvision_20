"""
Gerenciador de alertas GPIO para Raspberry Pi.
No Windows, simula os alertas via print no terminal.
"""

import threading
import time
from typing import Optional

from config import GPIO_PIN_ALERT, GPIO_PIN_SYSTEM_READY, GPIO_BLINK_INTERVAL, GPIO_ALERT_DURATION

# Detecta plataforma
import platform
IS_LINUX = platform.system() == "Linux"


class GPIOAlertManager:
    """Gerenciador de alertas GPIO para Raspberry Pi."""

    def __init__(self):
        self.is_raspberry_pi = self._detect_raspberry_pi()
        self.gpio_available = False
        self._alert_thread: Optional[threading.Thread] = None
        self._alert_active = False
        self._system_ready = False

        if self.is_raspberry_pi:
            self._setup_gpio()
        else:
            print("[GPIO] Modo simulado ativo (Windows/nao-Raspberry)")

    def _detect_raspberry_pi(self) -> bool:
        """Detecta se esta rodando no Raspberry Pi."""
        if not IS_LINUX:
            return False
        try:
            with open('/proc/cpuinfo', 'r') as f:
                content = f.read()
                return 'Raspberry' in content or 'BCM' in content
        except:
            return False

    def _setup_gpio(self) -> None:
        """Configura os pinos GPIO no Raspberry Pi."""
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(GPIO_PIN_ALERT, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(GPIO_PIN_SYSTEM_READY, GPIO.OUT, initial=GPIO.LOW)
            self.gpio_available = True
            print(f"[GPIO] Configurado: Alerta=GPIO{GPIO_PIN_ALERT}, Sistema=GPIO{GPIO_PIN_SYSTEM_READY}")
        except ImportError:
            print("[GPIO] RPi.GPIO nao disponivel - modo simulado")
        except Exception as e:
            print(f"[GPIO] Erro ao configurar: {e} - modo simulado")

    def set_system_ready(self, ready: bool) -> None:
        """Liga/desliga indicador de sistema configurado (GPIO 20)."""
        self._system_ready = ready
        if self.is_raspberry_pi and self.gpio_available:
            self.GPIO.output(GPIO_PIN_SYSTEM_READY, self.GPIO.HIGH if ready else self.GPIO.LOW)
        else:
            status = "LIGADO" if ready else "DESLIGADO"
            print(f"[GPIO SIMULADO] Sistema configurado: {status} (GPIO {GPIO_PIN_SYSTEM_READY})")

    def start_risk_alert(self) -> None:
        """Inicia pisca-pisca de alerta (GPIO 16)."""
        # Verifica se ja existe um alerta em execucao
        if self._alert_thread is not None and self._alert_thread.is_alive():
            return  # Ja esta piscando

        self._alert_active = True
        self._alert_thread = threading.Thread(target=self._alert_blink_loop, daemon=True)
        self._alert_thread.start()

    def stop_risk_alert(self) -> None:
        """Para o pisca-pisca de alerta."""
        self._alert_active = False
        if self._alert_thread is not None and self._alert_thread.is_alive():
            self._alert_thread.join(timeout=1.0)
        self._alert_thread = None

        # Garante que LED fica desligado
        if self.is_raspberry_pi and self.gpio_available:
            self.GPIO.output(GPIO_PIN_ALERT, self.GPIO.LOW)

    def _alert_blink_loop(self) -> None:
        """Loop que pisca o LED de alerta por tempo limitado."""
        blink_state = False
        start_time = time.time()

        while self._alert_active:
            # Verifica se excedeu a duracao maxima
            elapsed = time.time() - start_time
            if elapsed >= GPIO_ALERT_DURATION:
                print(f"[GPIO] Alerta encerrado apos {GPIO_ALERT_DURATION}s")
                break

            blink_state = not blink_state
            if self.is_raspberry_pi and self.gpio_available:
                self.GPIO.output(GPIO_PIN_ALERT, self.GPIO.HIGH if blink_state else self.GPIO.LOW)
            else:
                status = "LIGADO" if blink_state else "DESLIGADO"
                remaining = int(GPIO_ALERT_DURATION - elapsed)
                print(f"[GPIO SIMULADO] Alerta: {status} (GPIO {GPIO_PIN_ALERT}) - {remaining}s restantes")

            time.sleep(GPIO_BLINK_INTERVAL)

        # Garante LED desligado ao finalizar
        self._alert_active = False
        if self.is_raspberry_pi and self.gpio_available:
            self.GPIO.output(GPIO_PIN_ALERT, self.GPIO.LOW)

    def cleanup(self) -> None:
        """Limpa recursos GPIO ao encerrar."""
        self.stop_risk_alert()
        self.set_system_ready(False)

        if self.is_raspberry_pi and self.gpio_available:
            try:
                self.GPIO.cleanup([GPIO_PIN_ALERT, GPIO_PIN_SYSTEM_READY])
                print("[GPIO] Recursos liberados")
            except:
                pass
