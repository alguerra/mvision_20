"""
Testes da maquina de estados PoseStateMachineEMA (comportamento fail-safe).

Rodar da raiz do projeto:
    python -m unittest tests.test_pose_state_machine -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.pose_analyzer import BodyPoints, PoseStateMachineEMA, PositionAnalysis
import config


def make_analysis(
    inside: int = 8,
    outside: int = 0,
    core_visible: bool = True,
    neck_in: bool = True,
    hip_in: bool = True,
    standing: bool = False,
    sitting: bool = False,
    containment: float = 1.0,
) -> PositionAnalysis:
    """Constroi PositionAnalysis sintetica coerente."""
    a = PositionAnalysis()
    a.core_points_visible = core_visible
    a.occluded_mode = False
    a.neck_in_bed = neck_in if core_visible else None
    a.hip_in_bed = hip_in if core_visible else None
    a.points_inside = inside
    a.points_outside = outside
    a.points_monitored = inside + outside
    a.all_monitored_in_bed = a.points_monitored > 0 and outside == 0
    a.any_outside_bed = outside > 0
    a.all_outside_bed = a.points_monitored > 0 and inside == 0
    a.is_standing = standing
    a.is_sitting = sitting
    a.person_bed_containment = containment
    return a


SAFE = dict(inside=8, outside=0, neck_in=True, hip_in=True)
ALL_OUT = dict(inside=0, outside=8, neck_in=False, hip_in=False)
PARTIAL_OUT = dict(inside=5, outside=3, neck_in=True, hip_in=True)
WEAK = dict(inside=0, outside=0, core_visible=False)  # pessoa sem keypoints


class FSMTestBase(unittest.TestCase):
    def setUp(self):
        self.fsm = PoseStateMachineEMA()
        self.body = BodyPoints()

    def feed(self, analysis_kwargs, frames: int = 1, person_count: int = 1):
        state = None
        for _ in range(frames):
            analysis = make_analysis(**analysis_kwargs) if analysis_kwargs is not None else None
            body = self.body if analysis_kwargs is not None else None
            state = self.fsm.update(analysis, body, person_count)
        return state

    def confirm_patient(self):
        self.feed(SAFE, frames=15)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)
        self.assertTrue(self.fsm.patient_confirmed)


class TestPatientConfirmation(FSMTestBase):
    def test_confirms_patient_in_bed(self):
        self.confirm_patient()

    def test_passerby_standing_does_not_confirm(self):
        # Pessoa em pe fora da cama nunca vira paciente
        self.feed(dict(inside=0, outside=8, neck_in=False, hip_in=False,
                       standing=True, containment=0.1), frames=30)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)


class TestFailSafeAlertLatch(FSMTestBase):
    """Cenario critico: queda real = paciente some durante o alerta."""

    def _enter_alert(self):
        self.confirm_patient()
        self.feed(ALL_OUT, frames=10)
        self.assertIn(
            self.fsm.current_state,
            (PoseStateMachineEMA.RISCO_POTENCIAL, PoseStateMachineEMA.PACIENTE_FORA),
        )

    def test_fall_then_disappear_escalates_never_clears(self):
        self._enter_alert()
        # Paciente rasteja para fora do campo de visao: 60 frames sem ninguem
        for _ in range(60):
            self.fsm.update(None, None, 0)
            self.assertNotIn(
                self.fsm.current_state,
                (PoseStateMachineEMA.AGUARDANDO, PoseStateMachineEMA.MONITORANDO),
                "Alerta foi silenciado por ausencia de evidencia (falha fail-safe)",
            )
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)

    def test_weak_keypoints_during_alert_never_clears(self):
        self._enter_alert()
        # Pessoa visivel mas keypoints fracos (blur/oclusao durante queda)
        for _ in range(60):
            self.feed(WEAK, frames=1)
            self.assertNotIn(
                self.fsm.current_state,
                (PoseStateMachineEMA.AGUARDANDO, PoseStateMachineEMA.MONITORANDO),
                "insufficient_data cancelou alerta ativo (falha fail-safe)",
            )

    def test_persistent_alert_exits_only_with_positive_evidence(self):
        self._enter_alert()
        for _ in range(60):
            self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)

        # Menos frames seguros que o exigido: continua em alerta
        self.feed(SAFE, frames=config.ALERT_PERSISTENT_SAFE_FRAMES - 1)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.ALERTA_PERSISTENTE)

        # Evidencia segura suficiente: volta a monitorar
        self.feed(SAFE, frames=2)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)
        self.assertTrue(self.fsm.patient_confirmed)

    def test_manual_reset_clears_persistent_alert(self):
        self._enter_alert()
        for _ in range(60):
            self.fsm.update(None, None, 0)
        self.fsm.reset()
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)


class TestOcclusionInBed(FSMTestBase):
    def test_covered_patient_stays_monitored(self):
        """Paciente coberto por cobertor nao vira 'cama vazia' nem alerta."""
        self.confirm_patient()
        for _ in range(100):
            self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)
        self.assertTrue(self.fsm.occlusion_presumed)

    def test_occlusion_times_out_to_aguardando(self):
        self.confirm_patient()
        for _ in range(config.FRAMES_TO_LOSE_PATIENT + config.OCCLUSION_EMPTY_TIMEOUT_FRAMES + 5):
            self.fsm.update(None, None, 0)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.AGUARDANDO)

    def test_sudden_vanish_with_last_position_outside_goes_to_risk(self):
        self.confirm_patient()
        self.fsm._last_core_in_bed = False
        for _ in range(config.FRAMES_TO_LOSE_PATIENT + 1):
            self.fsm.update(None, None, 0)
        self.assertIn(
            self.fsm.current_state,
            (PoseStateMachineEMA.RISCO_POTENCIAL, PoseStateMachineEMA.ALERTA_PERSISTENTE),
        )


class TestCompanionMode(FSMTestBase):
    def test_companion_does_not_reset_patient(self):
        self.confirm_patient()
        # Acompanhante entra (2 pessoas), paciente segue seguro na cama
        state = self.feed(SAFE, frames=10, person_count=2)
        self.assertTrue(self.fsm.patient_confirmed)
        self.assertTrue(self.fsm.companion_present)
        self.assertEqual(state, PoseStateMachineEMA.ACOMPANHADO)
        # Estado interno continua MONITORANDO (analise ativa)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)

    def test_fall_with_companion_present_still_alerts(self):
        """Achado central da auditoria: queda com visita no quarto."""
        self.confirm_patient()
        self.feed(SAFE, frames=10, person_count=2)
        # Paciente cai da cama com acompanhante presente
        self.feed(ALL_OUT, frames=10, person_count=2)
        self.assertIn(
            self.fsm.current_state,
            (PoseStateMachineEMA.RISCO_POTENCIAL, PoseStateMachineEMA.PACIENTE_FORA),
            "Sistema ficou cego para queda com acompanhante presente",
        )

    def test_companion_leaves_no_blind_window(self):
        self.confirm_patient()
        self.feed(SAFE, frames=10, person_count=2)
        # Acompanhante sai; paciente permanece deitado
        state = self.feed(SAFE, frames=10, person_count=1)
        self.assertTrue(self.fsm.patient_confirmed,
                        "Saida do acompanhante resetou patient_confirmed (janela cega)")
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.MONITORANDO)
        self.assertEqual(state, PoseStateMachineEMA.MONITORANDO)

    def test_single_frame_double_detection_does_not_flap(self):
        self.confirm_patient()
        # Blip de 1 frame com 2 deteccoes (duplicata do YOLO)
        self.feed(SAFE, frames=1, person_count=2)
        state = self.feed(SAFE, frames=3, person_count=1)
        self.assertEqual(state, PoseStateMachineEMA.MONITORANDO)
        self.assertFalse(self.fsm.companion_present)


class TestPublication(FSMTestBase):
    def test_critical_alert_publishes_immediately(self):
        self.confirm_patient()
        self.feed(ALL_OUT, frames=15)
        self.assertEqual(self.fsm.current_state, PoseStateMachineEMA.PACIENTE_FORA)
        self.assertEqual(self.fsm.published_state, PoseStateMachineEMA.PACIENTE_FORA)

    def test_published_state_requires_dwell(self):
        # Publicacao de estados nao-criticos exige persistencia minima
        self.feed(SAFE, frames=1)
        # 1 frame de MONITORANDO candidato nao publica ainda
        self.assertEqual(self.fsm.published_state, PoseStateMachineEMA.AGUARDANDO)


class TestLegacyMode(FSMTestBase):
    def setUp(self):
        super().setUp()
        self.fsm._companion_analysis = False

    def test_legacy_multi_person_becomes_acompanhado(self):
        self.confirm_patient()
        state = self.feed(None, frames=7, person_count=2)
        self.assertEqual(state, PoseStateMachineEMA.ACOMPANHADO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
