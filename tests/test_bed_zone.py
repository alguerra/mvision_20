"""
Testes da zona da cama (modules/bed_zone) e da proveniencia da referencia.

Rodar da raiz do projeto:
    python -m unittest tests.test_bed_zone -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules import bed_zone
from modules.bed_detector import BedDetector
from modules.bed_zone import (
    bbox_touches_edges,
    containment,
    expand_bed_bbox,
    point_in_zone,
)

BED = (200, 250, 600, 470)  # w=400, h=220
FRAME = (640, 480)


class TestExpandBedBbox(unittest.TestCase):
    def test_matches_asymmetric_margins(self):
        ex1, ey1, ex2, ey2 = expand_bed_bbox(BED)
        self.assertAlmostEqual(ex1, 200 - 400 * config.BED_MARGIN_LEFT)
        self.assertAlmostEqual(ex2, 600 + 400 * config.BED_MARGIN_RIGHT)
        self.assertAlmostEqual(ey1, 250 - 220 * config.BED_MARGIN_TOP)
        self.assertAlmostEqual(ey2, 470 + 220 * config.BED_MARGIN_BOTTOM)

    def test_clamped_to_frame(self):
        ex1, ey1, ex2, ey2 = expand_bed_bbox((252, 306, 639, 479), FRAME)
        self.assertGreaterEqual(ex1, 0)
        self.assertGreaterEqual(ey1, 0)
        self.assertLessEqual(ex2, 639)
        self.assertLessEqual(ey2, 479)

    def test_point_in_zone_uses_top_margin(self):
        # Pescoco 20% acima do topo: dentro (margem topo 30%), mas 40% fora
        self.assertTrue(point_in_zone((400, 250 - 220 * 0.20), BED))
        self.assertFalse(point_in_zone((400, 250 - 220 * 0.40), BED))
        # Lateral: 5% fora esta dentro (margem 10%), 15% fora nao
        self.assertTrue(point_in_zone((200 - 400 * 0.05, 350), BED))
        self.assertFalse(point_in_zone((200 - 400 * 0.15, 350), BED))


class TestContainment(unittest.TestCase):
    def test_fully_inside_and_outside(self):
        self.assertAlmostEqual(containment((300, 300, 400, 400), BED), 1.0)
        self.assertAlmostEqual(containment((0, 0, 50, 50), BED), 0.0)

    def test_half_inside(self):
        # Pessoa 100 px de largura, metade dentro da borda esquerda
        self.assertAlmostEqual(containment((150, 300, 250, 400), BED), 0.5)

    def test_degenerate_person(self):
        self.assertEqual(containment((10, 10, 10, 10), BED), 0.0)


class TestTouchesEdges(unittest.TestCase):
    def test_reference_from_field_touches_right_and_bottom(self):
        self.assertEqual(bbox_touches_edges((252, 306, 639, 479), FRAME),
                         ["right", "bottom"])

    def test_centered_bed_touches_nothing(self):
        self.assertEqual(bbox_touches_edges(BED, FRAME), [])


class TestBedScoreEdgePenalty(unittest.TestCase):
    def setUp(self):
        self.det = BedDetector()

    def test_bottom_edge_not_penalized(self):
        import numpy as np
        centered = np.array([120, 130, 520, 350], dtype=float)
        bottom = np.array([120, 259, 520, 479], dtype=float)  # mesma area, toca a base
        s_center = self.det._calculate_bed_score(centered, 480, 640, 0.1)
        s_bottom = self.det._calculate_bed_score(bottom, 480, 640, 0.1)
        # So difere pelo termo de centralizacao (nenhuma penalidade de borda)
        self.assertGreater(s_bottom, s_center * 0.8)

    def test_side_edge_penalty_is_mild(self):
        import numpy as np
        inner = np.array([10, 100, 410, 400], dtype=float)
        at_left = np.array([0, 100, 400, 400], dtype=float)
        s_inner = self.det._calculate_bed_score(inner, 480, 640, 0.1)
        s_left = self.det._calculate_bed_score(at_left, 480, 640, 0.1)
        self.assertLess(s_left, s_inner)
        self.assertGreater(s_left, s_inner * 0.85)


class TestSensitivityMapping(unittest.TestCase):
    def test_anchor_levels(self):
        m = BedDetector.sensitivity_multiplier
        self.assertAlmostEqual(m(1), 4.0)
        self.assertAlmostEqual(m(5), 1.0)
        self.assertAlmostEqual(m(10), 0.3)

    def test_monotonic_and_clamped(self):
        m = BedDetector.sensitivity_multiplier
        values = [m(s) for s in range(1, 11)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertAlmostEqual(m(0), m(1))
        self.assertAlmostEqual(m(99), m(10))


class TestReferenceProvenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bed_reference.json"
        self.det = BedDetector()
        self.det.reference_path = self.path

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f)

    def test_legacy_reference_without_provenance_is_accepted(self):
        self._write({"bbox": [252, 306, 639, 479], "timestamp": 1.0,
                     "detected_class": "bed", "detected_strategy": "primary"})
        self.assertEqual(self.det.load_reference(frame_size=FRAME), (252, 306, 639, 479))
        self.assertIsNone(self.det.reference_sensitivity)
        self.assertTrue(self.det.reference_matches_sensitivity())

    def test_resolution_mismatch_rejected(self):
        self._write({"bbox": [100, 100, 300, 300], "frame_size": [1280, 720],
                     "flip_horizontal": config.FLIP_HORIZONTAL})
        self.assertIsNone(self.det.load_reference(frame_size=FRAME))

    def test_flip_mismatch_rejected(self):
        self._write({"bbox": [100, 100, 300, 300], "frame_size": [640, 480],
                     "flip_horizontal": not config.FLIP_HORIZONTAL})
        self.assertIsNone(self.det.load_reference(frame_size=FRAME))

    def test_sensitivity_mismatch_detected(self):
        self._write({"bbox": [100, 100, 300, 300], "frame_size": [640, 480],
                     "flip_horizontal": config.FLIP_HORIZONTAL,
                     "sensitivity": config.BED_DETECTION_SENSITIVITY + 1})
        self.assertIsNotNone(self.det.load_reference(frame_size=FRAME))
        self.assertFalse(self.det.reference_matches_sensitivity())

    def test_save_records_provenance_and_edges(self):
        self.det.detected_class_name = "bed"
        self.det._last_strategy_name = "coco_histEq"
        self.det._accept_detection((252, 306, 639, 479), "bed", 0.12, 0.3)
        data = self.det.save_reference((252, 306, 639, 479), frame_size=FRAME)
        self.assertEqual(data["frame_size"], [640, 480])
        self.assertEqual(data["sensitivity"], config.BED_DETECTION_SENSITIVITY)
        self.assertEqual(data["detected_strategy"], "coco_histEq")
        self.assertEqual(data["touches_edges"], ["right", "bottom"])
        with open(self.path) as f:
            self.assertEqual(json.load(f)["bbox"], [252, 306, 639, 479])


if __name__ == "__main__":
    unittest.main(verbosity=2)
