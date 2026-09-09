"""Testes da anonimizacao de rosto/cabeca (modules/privacy.py)."""
import unittest

import numpy as np

from modules.privacy import (
    apply_face_privacy, head_circle, mask_head,
    MASK_MIN_RADIUS, MASK_COLOR, SOLID_FALLBACK_RADIUS,
)


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


def checker(h=240, w=320, cell=4):
    """Frame xadrez preto/branco: alta variancia local em qualquer ponto."""
    yy, xx = np.mgrid[0:h, 0:w]
    m = (((yy // cell) + (xx // cell)) % 2).astype(np.uint8) * 255
    return np.dstack([m, m, m]).copy()


def local_std(img, cx, cy, r):
    return float(img[cy - r:cy + r, cx - r:cx + r].astype(float).std())


class TestApplyFacePrivacy(unittest.TestCase):
    def test_cobre_regiao_da_cabeca_de_todas_as_pessoas(self):
        for style in ("pixelate", "blur", "solid"):
            frame = checker()
            before = local_std(frame, 100, 47, 8)
            kp1, conf1 = make_kp()
            kp2 = kp1.copy(); kp2[:, 0] += 150  # segunda pessoa deslocada
            out = apply_face_privacy(
                frame, [(kp1, conf1, None), (kp2, conf1, None)], style=style
            )
            # detalhe fino (xadrez) some no centro do rosto das duas pessoas
            self.assertLess(local_std(out, 100, 47, 8), before * 0.5, style)
            self.assertLess(local_std(out, 250, 47, 8), before * 0.5, style)
            # fora da cabeca o frame continua intacto
            self.assertGreater(local_std(out, 100, 200, 8), before * 0.9, style)

    def test_solid_pinta_cor_da_mascara(self):
        frame = checker()
        kp, conf = make_kp()
        out = apply_face_privacy(frame, [(kp, conf, None)], style="solid")
        self.assertTrue((out[47, 100] == MASK_COLOR).all())

    def test_raio_pequeno_cai_no_solido(self):
        frame = checker()
        mask_head(frame, 100, 100, SOLID_FALLBACK_RADIUS - 1, "pixelate")
        self.assertTrue((frame[100, 100] == MASK_COLOR).all())

    def test_estilo_desconhecido_vira_solido(self):
        frame = checker()
        mask_head(frame, 100, 100, 30, "xyz")
        self.assertTrue((frame[100, 100] == MASK_COLOR).all())

    def test_cabeca_na_borda_do_frame_nao_quebra(self):
        for style in ("pixelate", "blur"):
            frame = checker()
            mask_head(frame, 2, 2, 30, style)         # canto superior esquerdo
            mask_head(frame, 318, 238, 30, style)     # canto inferior direito
            mask_head(frame, -5, 120, 20, style)      # centro fora do frame
            self.assertLess(local_std(frame, 8, 8, 6), 60, style)

    def test_pessoa_sem_dados_nao_quebra(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        kp = np.zeros((17, 2)); conf = np.zeros(17)
        out = apply_face_privacy(frame, [(kp, conf, None)])
        self.assertEqual(out.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
