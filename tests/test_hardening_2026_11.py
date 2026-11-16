"""
Testes do hardening pos-auditoria de nov/2026:
  - faixa segura das configuracoes editaveis pelo painel (config.py)
  - latch de alerta persistido entre reinicios (main.py + FSM)
  - expiracao de todo episodio de alerta (aparelho sem teclado)

Rodar da raiz do projeto:
    python -m unittest tests.test_hardening_2026_11 -v
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules.pose_analyzer import PoseStateMachineEMA
from tests.test_pose_state_machine import FSMTestBase, SAFE, ALL_OUT


class TestRuntimeValueValidation(unittest.TestCase):
    def test_values_that_silence_the_alarm_are_rejected(self):
        for key, value in [
            ("EMA_ALPHA", 0),                     # scores congelados
            ("EMA_ALPHA", 1.5),
            ("EMA_THRESHOLD_ENTER_RISK", 5),      # nunca atingido
            ("EMA_THRESHOLD_ENTER_RISK", 0.0),
            ("BED_RECHECK_INTERVAL_HOURS", 0),    # recheck em todo frame
            ("BED_DETECTION_SENSITIVITY", 11),
            ("FRAMES_TO_LOSE_PATIENT", 100000),
            ("EMA_ALPHA", float("nan")),
        ]:
            ok, _ = config.validate_runtime_value(key, value)
            self.assertFalse(ok, f"{key}={value} deveria ser rejeitado")

    def test_type_checks(self):
        self.assertFalse(config.validate_runtime_value("FLIP_HORIZONTAL", 1)[0])
        self.assertFalse(config.validate_runtime_value("EMA_ALPHA", True)[0])
        self.assertFalse(config.validate_runtime_value("EMA_ALPHA", "0.3")[0])
        self.assertFalse(config.validate_runtime_value("BED_RECHECK_INTERVAL_HOURS", 2.5)[0])
        self.assertFalse(config.validate_runtime_value("DEV_MODE", True)[0])

    def test_valid_values_are_normalized(self):
        self.assertEqual(config.validate_runtime_value("EMA_ALPHA", 0.4), (True, 0.4))
        self.assertEqual(config.validate_runtime_value("EMA_ALPHA", 1 - 0.5), (True, 0.5))
        ok, v = config.validate_runtime_value("BED_RECHECK_INTERVAL_HOURS", 6.0)
        self.assertTrue(ok)
        self.assertIsInstance(v, int)
        self.assertEqual(config.validate_runtime_value("FLIP_HORIZONTAL", False), (True, False))

    def test_hysteresis_consistency(self):
        self.assertIsNotNone(config.validate_runtime_consistency(
            {"EMA_THRESHOLD_ENTER_RISK": 0.4, "EMA_THRESHOLD_EXIT_RISK": 0.5}))
        self.assertIsNone(config.validate_runtime_consistency(
            {"EMA_THRESHOLD_ENTER_RISK": 0.5, "EMA_THRESHOLD_EXIT_RISK": 0.3}))


class TestRuntimeOverlayRanges(unittest.TestCase):
    """O overlay aplicado no boot do monitor descarta valores fora da faixa."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self._tmp, "config"))
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)
        importlib.reload(config)  # restaura defaults para os outros testes

    def _load_with(self, overrides: dict):
        with open(os.path.join("config", "runtime_config.json"), "w", encoding="utf-8") as f:
            json.dump(overrides, f)
        return importlib.reload(config)

    def test_out_of_range_keeps_default_valid_applies(self):
        default_alpha = 0.3
        cfg = self._load_with({"EMA_ALPHA": 0, "BED_RECHECK_INTERVAL_HOURS": 12})
        self.assertEqual(cfg.EMA_ALPHA, default_alpha)
        self.assertEqual(cfg.BED_RECHECK_INTERVAL_HOURS, 12)

    def test_inverted_hysteresis_discards_both(self):
        cfg = self._load_with({"EMA_THRESHOLD_ENTER_RISK": 0.3,
                               "EMA_THRESHOLD_EXIT_RISK": 0.6})
        self.assertEqual(cfg.EMA_THRESHOLD_ENTER_RISK, 0.5)
        self.assertEqual(cfg.EMA_THRESHOLD_EXIT_RISK, 0.3)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestAlertExpiry(FSMTestBase):
    """Todo alerta expira: o aparelho nao tem teclado para reset manual."""

    MAX = 600

    def setUp(self):
        self.clock = FakeClock()
        self.fsm = PoseStateMachineEMA(alert_max_duration_seconds=self.MAX,
                                       clock=self.clock)
        from modules.pose_analyzer import BodyPoints
        self.body = BodyPoints()

    def _alert_then_vanish(self):
        self.confirm_patient()
        self.feed(ALL_OUT, frames=10)
        for _ in range(60):
            self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)

    def test_persistent_alert_expires_to_aguardando(self):
        self._alert_then_vanish()
        self.clock.t += self.MAX - 1
        self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)
        self.assertFalse(self.fsm.consume_alert_expired())
        self.clock.t += 2
        state = self.fsm.update(None, None, 0)
        self.assertEqual(state, PoseStateMachineEMA.AGUARDANDO)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)
        self.assertTrue(self.fsm.consume_alert_expired())
        self.assertFalse(self.fsm.consume_alert_expired())  # so uma vez

    def test_patient_still_out_of_bed_does_not_realert_after_expiry(self):
        self.confirm_patient()
        self.feed(ALL_OUT, frames=10)
        self.clock.t += self.MAX + 1
        self.feed(ALL_OUT, frames=1)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)
        # Paciente continua visivel fora da cama (ex.: poltrona): sem loop
        for _ in range(200):
            self.clock.t += 1
            self.feed(ALL_OUT, frames=1)
            self.assertNotIn(self.fsm.current_state, PoseStateMachineEMA.ALERT_STATES)

    def test_monitoring_resumes_after_expiry_when_patient_lies_down(self):
        self._alert_then_vanish()
        self.clock.t += self.MAX + 1
        self.fsm.update(None, None, 0)
        self.confirm_patient()
        # Novo episodio tem relogio proprio
        self.feed(ALL_OUT, frames=10)
        self.assertIn(self.fsm.current_state, PoseStateMachineEMA.ALERT_STATES)
        self.clock.t += self.MAX - 10
        self.feed(ALL_OUT, frames=1)
        self.assertIn(self.fsm.current_state, PoseStateMachineEMA.ALERT_STATES)

    def test_episode_spans_escalation(self):
        # RISCO -> FORA -> PERSISTENTE contam como um so episodio
        self.confirm_patient()
        self.feed(ALL_OUT, frames=3)  # EMA alpha=0.3: 3 frames cruzam o limiar
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.RISCO_POTENCIAL)
        self.clock.t += self.MAX / 2
        self.feed(ALL_OUT, frames=10)
        for _ in range(30):
            self.fsm.update(None, None, 0)
        self.clock.t += self.MAX / 2
        self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)

    def test_resolved_alert_resets_episode_clock(self):
        self.confirm_patient()
        self.feed(ALL_OUT, frames=10)
        self.clock.t += self.MAX - 5
        self.feed(SAFE, frames=40)  # voltou para a cama
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)
        self.feed(ALL_OUT, frames=10)  # novo episodio
        self.clock.t += 10
        self.feed(ALL_OUT, frames=1)
        self.assertIn(self.fsm.current_state, PoseStateMachineEMA.ALERT_STATES)

    def test_restored_alert_expires_counting_time_before_restart(self):
        self.fsm.restore_persistent_alert(elapsed_seconds=self.MAX - 30)
        self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)
        self.clock.t += 31
        self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)


class TestRestoredAlertFSM(FSMTestBase):
    def test_restored_alert_survives_absence_of_evidence(self):
        self.fsm.restore_persistent_alert()
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)
        for _ in range(100):
            self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)
        self.feed(ALL_OUT, frames=30)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)

    def test_restored_alert_clears_with_patient_back_in_bed(self):
        self.fsm.restore_persistent_alert()
        self.feed(SAFE, frames=config.ALERT_PERSISTENT_SAFE_FRAMES + 1)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)


def _import_main():
    """Importa main.py sem exigir ultralytics/torch no ambiente de teste."""
    if "ultralytics" not in sys.modules:
        try:
            import ultralytics  # noqa: F401
        except ImportError:
            sys.modules["ultralytics"] = types.SimpleNamespace(YOLO=object)
    import main
    return main


class TestAlertLatchPersistence(unittest.TestCase):
    def setUp(self):
        self.main = _import_main()
        self._tmp = tempfile.mkdtemp()
        self._orig_path = self.main.ALERT_LATCH_PATH
        self.main.ALERT_LATCH_PATH = os.path.join(self._tmp, "data", "alert_latch.json")

    def tearDown(self):
        self.main.ALERT_LATCH_PATH = self._orig_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_roundtrip_and_clear(self):
        self.assertIsNone(self.main.load_alert_latch())
        self.main.save_alert_latch(True, "PACIENTE_FORA")
        latch = self.main.load_alert_latch()
        self.assertIsNotNone(latch)
        self.assertEqual(latch["state"], "PACIENTE_FORA")
        self.main.save_alert_latch(False, "MONITORANDO")
        self.assertIsNone(self.main.load_alert_latch())

    def test_corrupted_latch_is_treated_as_active(self):
        os.makedirs(os.path.dirname(self.main.ALERT_LATCH_PATH))
        with open(self.main.ALERT_LATCH_PATH, "w") as f:
            f.write('{"active": tr')  # truncado por queda de energia
        self.assertIsNotNone(self.main.load_alert_latch())

    def test_elapsed_time_is_reported(self):
        self.main.save_alert_latch(True, "PACIENTE_FORA")
        with open(self.main.ALERT_LATCH_PATH, "r") as f:
            data = json.load(f)
        half = self.main.ALERT_MAX_DURATION_SECONDS / 2
        data["timestamp"] = time.time() - half
        with open(self.main.ALERT_LATCH_PATH, "w") as f:
            json.dump(data, f)
        latch = self.main.load_alert_latch()
        self.assertIsNotNone(latch)
        self.assertAlmostEqual(latch["elapsed_seconds"], half, delta=2)

    def test_expired_latch_is_discarded(self):
        self.main.save_alert_latch(True, "RISCO_POTENCIAL")
        with open(self.main.ALERT_LATCH_PATH, "r") as f:
            data = json.load(f)
        data["timestamp"] = time.time() - (self.main.ALERT_MAX_DURATION_SECONDS + 1)
        with open(self.main.ALERT_LATCH_PATH, "w") as f:
            json.dump(data, f)
        self.assertIsNone(self.main.load_alert_latch())
        self.assertFalse(os.path.exists(self.main.ALERT_LATCH_PATH))

    def test_clock_went_backwards_keeps_latch(self):
        self.main.save_alert_latch(True, "PACIENTE_FORA")
        with open(self.main.ALERT_LATCH_PATH, "r") as f:
            data = json.load(f)
        data["timestamp"] = time.time() + 30 * 24 * 3600  # sem RTC
        with open(self.main.ALERT_LATCH_PATH, "w") as f:
            json.dump(data, f)
        latch = self.main.load_alert_latch()
        self.assertIsNotNone(latch)
        self.assertEqual(latch["elapsed_seconds"], 0.0)  # mas ainda expira


if __name__ == "__main__":
    unittest.main()
