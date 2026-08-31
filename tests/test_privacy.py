"""Testes da anonimizacao de rosto/cabeca (modules/privacy.py)."""
import unittest

import numpy as np

from modules.privacy import apply_face_privacy, head_circle, MASK_MIN_RADIUS


def make_kp(head=True, shoulders=True):
    """Keypoints COCO-17 sinteticos de pessoa ereta com cabeca em (100, 50)."""
    kp = np.zeros((17, 2), dtype=float)
    conf = np.zeros(17, dtype=float)
    if head:
        kp[0] = (100, 50)   # nariz
        kp[1] = (95, 45)    # olho E
        kp[2] = (105, 45)   # olho D
        conf[0:3] = 0.9
    if shoulders:
        kp[5] = (80, 90)
        kp[6] = (120, 90)
        conf[5:7] = 0.9
    return kp, conf


class TestHeadCircle(unittest.TestCase):
    def test_cabeca_visivel_centra_no_rosto(self):
        kp, conf = make_kp()
        cx, cy, r = head_circle(kp, conf)
        self.assertAlmostEqual(cx, 100, delta=5)
        self.assertAlmostEqual(cy, 47, delta=5)
        # raio cobre pelo menos metade da distancia entre ombros
        self.assertGreaterEqual(r, 0.5 * 40)

    def test_sem_cabeca_usa_ombros(self):
        kp, conf = make_kp(head=False)
        cx, cy, r = head_circle(kp, conf)
        self.assertAlmostEqual(cx, 100, delta=5)
        self.assertLess(cy, 90)  # acima do meio dos ombros
        self.assertGreaterEqual(r, MASK_MIN_RADIUS)

    def test_sem_keypoints_usa_topo_do_bbox(self):
        kp, conf = make_kp(head=False, shoulders=False)
        cx, cy, r = head_circle(kp, conf, bbox=(60, 30, 140, 200))
        self.assertEqual(cx, 100)
        self.assertLessEqual(cy, 30 + r + 1)  # faixa superior do bbox
        self.assertGreaterEqual(r, MASK_MIN_RADIUS)

    def test_sem_nada_retorna_none(self):
        kp, conf = make_kp(head=False, shoulders=False)
        self.assertIsNone(head_circle(kp, conf, bbox=None))

    def test_keypoint_zero_zero_ignorado(self):
        # (0,0) e a convencao do ultralytics para keypoint ausente
        kp, conf = make_kp(head=False, shoulders=False)
        conf[0] = 0.9  # conf alta mas coordenada (0,0) -> deve ser ignorado
        self.assertIsNone(head_circle(kp, conf))


class TestApplyFacePrivacy(unittest.TestCase):
    def test_pinta_regiao_da_cabeca_de_todas_as_pessoas(self):
        frame = np.full((240, 320, 3), 255, dtype=np.uint8)
        kp1, conf1 = make_kp()
        kp2 = kp1.copy(); kp2[:, 0] += 150  # segunda pessoa deslocada
        out = apply_face_privacy(frame, [(kp1, conf1, None), (kp2, conf1, None)])
        # centro do rosto das duas pessoas nao e mais branco
        self.assertFalse((out[47, 100] == 255).all())
        self.assertFalse((out[47, 250] == 255).all())

    def test_pessoa_sem_dados_nao_quebra(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        kp = np.zeros((17, 2)); conf = np.zeros(17)
        out = apply_face_privacy(frame, [(kp, conf, None)])
        self.assertEqual(out.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
