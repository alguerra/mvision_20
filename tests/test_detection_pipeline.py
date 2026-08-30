"""
Testes do pipeline de deteccao: NMS manual e selecao da pessoa-paciente.

Rodar da raiz do projeto:
    python -m unittest tests.test_detection_pipeline -v
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import (
    _filter_overlapping_boxes,
    _needs_ir_normalization,
    _select_patient_index,
    _should_accept_recheck,
)
from modules.bed_detector import BedDetector

FRAME_SHAPE = (480, 640, 3)
BED_BBOX = (200, 250, 600, 470)


class TestNMSIndexes(unittest.TestCase):
    def test_overlapping_boxes_keep_largest_real_index(self):
        # Deteccao 0 pequena, deteccao 1 grande e sobreposta: manter indice 1
        boxes = np.array([
            [300.0, 300.0, 400.0, 450.0],   # menor (IoU ~0.68 com a maior)
            [290.0, 290.0, 420.0, 460.0],   # maior (mesma pessoa)
        ])
        keep = _filter_overlapping_boxes(boxes, iou_threshold=0.4)
        self.assertEqual(len(keep), 1)
        # O indice retornado deve ser o da bbox de MAIOR area (1), nao o [0]
        self.assertEqual(keep[0], 1)

    def test_distinct_people_both_kept(self):
        boxes = np.array([
            [50.0, 50.0, 150.0, 400.0],
            [400.0, 100.0, 550.0, 450.0],
        ])
        keep = _filter_overlapping_boxes(boxes, iou_threshold=0.4)
        self.assertEqual(len(keep), 2)


class TestPatientSelection(unittest.TestCase):
    def test_selects_person_in_bed_over_standing_companion(self):
        boxes = np.array([
            [30.0, 60.0, 130.0, 460.0],      # acompanhante em pe, fora da cama
            [250.0, 280.0, 560.0, 450.0],    # paciente deitado na cama
        ])
        idx = _select_patient_index(boxes, [0, 1], BED_BBOX, None, FRAME_SHAPE)
        self.assertEqual(idx, 1)

    def test_no_one_near_bed_returns_none(self):
        # Apenas passantes longe da cama: nao ha paciente identificavel
        boxes = np.array([
            [10.0, 10.0, 90.0, 240.0],
            [100.0, 10.0, 170.0, 230.0],
        ])
        idx = _select_patient_index(boxes, [0, 1], BED_BBOX, None, FRAME_SHAPE)
        self.assertIsNone(idx)

    def test_continuity_bonus_prefers_previous_patient(self):
        # Duas pessoas parcialmente na cama; continuidade decide
        boxes = np.array([
            [220.0, 260.0, 380.0, 440.0],
            [420.0, 260.0, 580.0, 440.0],
        ])
        last_centroid = (500.0, 350.0)  # perto da deteccao 1
        idx = _select_patient_index(boxes, [0, 1], BED_BBOX, last_centroid, FRAME_SHAPE)
        self.assertEqual(idx, 1)


class TestIRNormalizationDecision(unittest.TestCase):
    """Normalizacao IR sob demanda: so em cena escura ou com cast de cor."""

    def test_dark_scene_needs_normalization(self):
        frame = np.full((480, 640, 3), 40, dtype=np.uint8)
        self.assertTrue(_needs_ir_normalization(frame))

    def test_bright_balanced_scene_skips_normalization(self):
        frame = np.full((480, 640, 3), 150, dtype=np.uint8)
        self.assertFalse(_needs_ir_normalization(frame))

    def test_ir_purple_cast_needs_normalization(self):
        # Cast tipico de camera IR: canal azul/vermelho muito acima do verde
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :, 0] = 180  # B
        frame[:, :, 1] = 110  # G
        frame[:, :, 2] = 170  # R
        self.assertTrue(_needs_ir_normalization(frame))


class TestAsetoValidation(unittest.TestCase):
    """Validacao cruzada COCO x ASETO na calibracao da cama."""

    def setUp(self):
        self.detector = BedDetector()  # sem modelos (lazy)

    def test_iou(self):
        self.assertAlmostEqual(
            BedDetector._bbox_iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        self.assertEqual(
            BedDetector._bbox_iou((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)

    def test_candidate_overlapping_aseto_is_validated(self):
        candidate = (250, 280, 560, 450)
        aseto = [(230, 260, 580, 470)]  # ASETO ve a cama no mesmo lugar
        self.assertTrue(self.detector._candidate_validated_by_aseto(candidate, aseto))

    def test_candidate_on_armchair_is_rejected(self):
        # COCO detectou a poltrona ("couch"); ASETO ve a cama em outro lugar
        candidate = (20, 100, 160, 300)
        aseto = [(250, 280, 560, 450)]
        self.assertFalse(self.detector._candidate_validated_by_aseto(candidate, aseto))

    def test_fail_open_when_aseto_unavailable_or_blind(self):
        candidate = (20, 100, 160, 300)
        # None = ASETO indisponivel; [] = ASETO rodou e nao viu nada
        self.assertTrue(self.detector._candidate_validated_by_aseto(candidate, None))
        self.assertTrue(self.detector._candidate_validated_by_aseto(candidate, []))


class TestRecheckAcceptance(unittest.TestCase):
    """Recheck so refina a referencia; nunca ratchet nem troca silenciosa."""

    CURRENT = (200, 250, 600, 470)

    def test_small_refinement_accepted(self):
        accept, reason = _should_accept_recheck(self.CURRENT, 0.10, (205, 245, 605, 468), 0.12)
        self.assertTrue(accept)
        self.assertEqual(reason, "refined")

    def test_growth_beyond_25pct_rejected(self):
        # Mesma posicao, mas abocanhou a mesa de cabeceira (+40% de area).
        # Com o criterio antigo (score cresce com a area) isto seria aceito.
        bigger = (200, 250, 760, 470)
        accept, reason = _should_accept_recheck(self.CURRENT, 0.10, bigger, 0.30)
        self.assertFalse(accept)
        self.assertEqual(reason, "area_change")

    def test_shrink_within_range_accepted(self):
        smaller = (210, 260, 590, 460)  # ~-14% de area
        accept, reason = _should_accept_recheck(self.CURRENT, 0.10, smaller, 0.10)
        self.assertTrue(accept)

    def test_lower_confidence_rejected(self):
        accept, reason = _should_accept_recheck(self.CURRENT, 0.20, (202, 252, 602, 472), 0.10)
        self.assertFalse(accept)
        self.assertEqual(reason, "lower_confidence")

    def test_moved_bed_flagged_not_replaced(self):
        moved = (20, 100, 300, 300)
        accept, reason = _should_accept_recheck(self.CURRENT, 0.10, moved, 0.50)
        self.assertFalse(accept)
        self.assertEqual(reason, "moved")

    def test_partial_overlap_rejected_as_low_iou(self):
        # Deslocada 180 px: IoU ~0.38, entre 0.3 e 0.5 — nem "movida" nem refinamento
        shifted = (380, 250, 780, 470)
        accept, reason = _should_accept_recheck(self.CURRENT, 0.10, shifted, 0.50)
        self.assertFalse(accept)
        self.assertEqual(reason, "low_iou")


if __name__ == "__main__":
    unittest.main(verbosity=2)
