"""
Módulo de interface visual com OpenCV.
Renderiza feed de vídeo, bboxes, dashboard de métricas e controles.

Suporta multiplataforma:
- Windows: GUI com cv2.imshow
- Linux/Raspberry Pi: Modo headless
"""

from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from config import DASHBOARD_WIDTH, WINDOW_NAME, POSE_CONFIDENCE_HIGH
from modules.state_machine import PatientState, PatientPoseState, StateMachine
from modules.camera import DisplayBase, DisplayOpenCV, create_display, IS_WINDOWS, IS_LINUX


class DisplayManager:
    """Gerenciador de interface visual com OpenCV."""

    # Cores padrão (BGR)
    COLOR_BED = (255, 150, 0)  # Azul claro
    COLOR_TEXT = (255, 255, 255)  # Branco
    COLOR_DASHBOARD_BG = (40, 40, 40)  # Cinza escuro
    COLOR_STATUS_BG = (0, 0, 0)  # Preto

    # Fontes
    FONT = cv2.FONT_HERSHEY_SIMPLEX
    FONT_SCALE_SMALL = 0.5
    FONT_SCALE_MEDIUM = 0.6
    FONT_SCALE_LARGE = 0.8

    def __init__(self, window_name: Optional[str] = None, headless: bool = False):
        """
        Inicializa o gerenciador de display.

        Args:
            window_name: Nome da janela. Default: config.WINDOW_NAME
            headless: Se True, força modo headless (sem GUI) - não recomendado
        """
        self.window_name = window_name or WINDOW_NAME
        self.dashboard_width = DASHBOARD_WIDTH

        # Cria backend de display - sempre GUI no uso normal
        # O sistema aguarda a GUI estar disponível antes de chegar aqui
        self._display: DisplayBase = create_display(headless=headless)
        self.headless = not isinstance(self._display, DisplayOpenCV)

        # Sempre renderiza no modo normal (GUI)
        self.skip_rendering = False

    def draw_bed_polygon(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        color: Optional[Tuple[int, int, int]] = None,
    ) -> np.ndarray:
        """
        Desenha retângulo da cama no frame.

        Args:
            frame: Frame de vídeo.
            bbox: Tuple (x1, y1, x2, y2) da cama.
            color: Cor BGR opcional.

        Returns:
            Frame com cama desenhada.
        """
        color = color or self.COLOR_BED
        x1, y1, x2, y2 = [int(v) for v in bbox]

        # Desenha retângulo com bordas arredondadas (simulado)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Label "CAMA"
        label = "CAMA"
        (w, h), _ = cv2.getTextSize(label, self.FONT, self.FONT_SCALE_SMALL, 1)
        cv2.rectangle(frame, (x1, y1 - h - 10), (x1 + w + 10, y1), color, -1)
        cv2.putText(
            frame,
            label,
            (x1 + 5, y1 - 5),
            self.FONT,
            self.FONT_SCALE_SMALL,
            (0, 0, 0),
            1,
        )

        return frame

    def draw_patient_bbox(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        color: Tuple[int, int, int],
        label: str = "PACIENTE",
    ) -> np.ndarray:
        """
        Desenha bbox do paciente no frame.

        Args:
            frame: Frame de vídeo.
            bbox: Tuple (x1, y1, x2, y2) do paciente.
            color: Cor BGR baseada no estado.
            label: Label a exibir.

        Returns:
            Frame com paciente desenhado.
        """
        x1, y1, x2, y2 = [int(v) for v in bbox]

        # Desenha retângulo
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Label
        (w, h), _ = cv2.getTextSize(label, self.FONT, self.FONT_SCALE_SMALL, 1)
        cv2.rectangle(frame, (x1, y1 - h - 10), (x1 + w + 10, y1), color, -1)
        cv2.putText(
            frame,
            label,
            (x1 + 5, y1 - 5),
            self.FONT,
            self.FONT_SCALE_SMALL,
            (0, 0, 0),
            1,
        )

        return frame

    def draw_dashboard(
        self,
        frame: np.ndarray,
        features: Optional[Dict[str, float]],
        state: PatientState,
        persons_count: int = 0,
    ) -> np.ndarray:
        """
        Desenha painel lateral com métricas.

        Args:
            frame: Frame de vídeo.
            features: Dict com features ou None.
            state: Estado atual do paciente.
            persons_count: Número de pessoas detectadas.

        Returns:
            Frame com dashboard.
        """
        h, w = frame.shape[:2]

        # Cria painel lateral
        dashboard = np.full((h, self.dashboard_width, 3), self.COLOR_DASHBOARD_BG, dtype=np.uint8)

        # Título
        cv2.putText(
            dashboard,
            "DASHBOARD",
            (10, 30),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            self.COLOR_TEXT,
            1,
        )
        cv2.line(dashboard, (10, 40), (self.dashboard_width - 10, 40), self.COLOR_TEXT, 1)

        # Estado atual
        state_color = self._get_state_color_bgr(state)
        cv2.putText(
            dashboard,
            f"Estado: {state.value}",
            (10, 70),
            self.FONT,
            self.FONT_SCALE_SMALL,
            state_color,
            1,
        )

        # Contagem de pessoas
        cv2.putText(
            dashboard,
            f"Pessoas: {persons_count}",
            (10, 100),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )

        # Separador
        cv2.line(dashboard, (10, 115), (self.dashboard_width - 10, 115), self.COLOR_TEXT, 1)

        # Features (se disponíveis)
        y_pos = 140
        if features:
            metrics = [
                ("rel_h", features.get("rel_height", 0)),
                ("y_top", features.get("y_top_norm", 0)),
                ("aspect", features.get("aspect_ratio", 0)),
                ("delta_y", features.get("delta_y_top", 0)),
                ("disp_x", features.get("disp_x", 0)),
                ("disp_y", features.get("disp_y", 0)),
            ]

            for name, value in metrics:
                text = f"{name}: {value:.2f}" if isinstance(value, float) else f"{name}: {value}"
                cv2.putText(
                    dashboard,
                    text,
                    (10, y_pos),
                    self.FONT,
                    self.FONT_SCALE_SMALL,
                    self.COLOR_TEXT,
                    1,
                )
                y_pos += 25
        else:
            cv2.putText(
                dashboard,
                "Sem dados",
                (10, y_pos),
                self.FONT,
                self.FONT_SCALE_SMALL,
                (128, 128, 128),
                1,
            )

        # Controles no final
        y_pos = h - 100
        cv2.line(dashboard, (10, y_pos - 10), (self.dashboard_width - 10, y_pos - 10), self.COLOR_TEXT, 1)
        cv2.putText(
            dashboard,
            "CONTROLES",
            (10, y_pos + 10),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )

        controls = ["[S] Sitting", "[L] Lying", "[F] Fall", "[N] Normal", "[Q] Quit"]
        for i, ctrl in enumerate(controls):
            cv2.putText(
                dashboard,
                ctrl,
                (10, y_pos + 30 + i * 15),
                self.FONT,
                0.4,
                (200, 200, 200),
                1,
            )

        # Concatena dashboard ao frame
        return np.hstack([frame, dashboard])

    def draw_status(
        self,
        frame: np.ndarray,
        status_text: str,
        color: Optional[Tuple[int, int, int]] = None,
    ) -> np.ndarray:
        """
        Desenha barra de status no topo do frame.

        Args:
            frame: Frame de vídeo.
            status_text: Texto de status.
            color: Cor de fundo opcional.

        Returns:
            Frame com status.
        """
        h, w = frame.shape[:2]
        color = color or self.COLOR_STATUS_BG

        # Barra de status
        cv2.rectangle(frame, (0, 0), (w, 35), color, -1)

        # Texto
        cv2.putText(
            frame,
            status_text,
            (10, 25),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            self.COLOR_TEXT,
            1,
        )

        return frame

    def draw_standby(self, frame: np.ndarray) -> np.ndarray:
        """
        Desenha tela de stand-by quando cama não é detectada.

        Args:
            frame: Frame de vídeo.

        Returns:
            Frame com mensagem de stand-by.
        """
        h, w = frame.shape[:2]

        # Overlay escuro
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        # Mensagem central
        text = "STAND-BY"
        subtext = "Cama nao localizada - Aguardando..."

        (tw, th), _ = cv2.getTextSize(text, self.FONT, 1.5, 2)
        cv2.putText(
            frame,
            text,
            ((w - tw) // 2, h // 2 - 20),
            self.FONT,
            1.5,
            (0, 255, 255),
            2,
        )

        (stw, sth), _ = cv2.getTextSize(subtext, self.FONT, self.FONT_SCALE_MEDIUM, 1)
        cv2.putText(
            frame,
            subtext,
            ((w - stw) // 2, h // 2 + 30),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            self.COLOR_TEXT,
            1,
        )

        return frame

    def draw_system_message(
        self,
        frame: np.ndarray,
        title: str,
        subtitle: str,
        color: Tuple[int, int, int] = (0, 255, 255),
    ) -> np.ndarray:
        """
        Desenha mensagem centralizada do sistema.

        Args:
            frame: Frame de vídeo.
            title: Título principal.
            subtitle: Subtítulo.
            color: Cor do título (BGR).

        Returns:
            Frame com mensagem centralizada.
        """
        h, w = frame.shape[:2]

        # Overlay escuro
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        # Título
        (tw, th), _ = cv2.getTextSize(title, self.FONT, 1.2, 2)
        cv2.putText(
            frame,
            title,
            ((w - tw) // 2, h // 2 - 30),
            self.FONT,
            1.2,
            color,
            2,
        )

        # Subtítulo
        (stw, sth), _ = cv2.getTextSize(subtitle, self.FONT, self.FONT_SCALE_MEDIUM, 1)
        cv2.putText(
            frame,
            subtitle,
            ((w - stw) // 2, h // 2 + 20),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            self.COLOR_TEXT,
            1,
        )

        return frame

    def draw_calibration_progress(
        self,
        frame: np.ndarray,
        progress_text: str,
        current: int,
        total: int,
    ) -> np.ndarray:
        """
        Desenha progresso da calibração com barra.

        Args:
            frame: Frame de vídeo.
            progress_text: Texto de status.
            current: Progresso atual.
            total: Total para completar.

        Returns:
            Frame com barra de progresso.
        """
        h, w = frame.shape[:2]

        # Overlay escuro
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        # Título
        title = "CONFIGURANDO SISTEMA"
        (tw, th), _ = cv2.getTextSize(title, self.FONT, 1.2, 2)
        cv2.putText(
            frame,
            title,
            ((w - tw) // 2, h // 2 - 60),
            self.FONT,
            1.2,
            (0, 255, 255),
            2,
        )

        # Subtítulo
        subtitle = "Calibrando posicao da cama..."
        (stw, sth), _ = cv2.getTextSize(subtitle, self.FONT, self.FONT_SCALE_MEDIUM, 1)
        cv2.putText(
            frame,
            subtitle,
            ((w - stw) // 2, h // 2 - 20),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            self.COLOR_TEXT,
            1,
        )

        # Barra de progresso
        bar_width = 300
        bar_height = 20
        bar_x = (w - bar_width) // 2
        bar_y = h // 2 + 20

        # Background da barra
        cv2.rectangle(
            frame,
            (bar_x, bar_y),
            (bar_x + bar_width, bar_y + bar_height),
            (80, 80, 80),
            -1,
        )

        # Progresso
        progress_width = int((current / total) * bar_width)
        cv2.rectangle(
            frame,
            (bar_x, bar_y),
            (bar_x + progress_width, bar_y + bar_height),
            (0, 255, 0),
            -1,
        )

        # Borda da barra
        cv2.rectangle(
            frame,
            (bar_x, bar_y),
            (bar_x + bar_width, bar_y + bar_height),
            self.COLOR_TEXT,
            1,
        )

        # Texto de progresso
        (ptw, pth), _ = cv2.getTextSize(progress_text, self.FONT, self.FONT_SCALE_SMALL, 1)
        cv2.putText(
            frame,
            progress_text,
            ((w - ptw) // 2, bar_y + bar_height + 30),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )

        return frame

    def draw_log_feedback(
        self,
        frame: np.ndarray,
        label: str,
        event_count: int,
    ) -> np.ndarray:
        """
        Desenha feedback visual quando evento é logado.

        Args:
            frame: Frame de vídeo.
            label: Label do evento registrado.
            event_count: Número do evento.

        Returns:
            Frame com feedback.
        """
        h, w = frame.shape[:2]

        # Box de feedback
        text = f"Evento #{event_count} - {label}"
        (tw, th), _ = cv2.getTextSize(text, self.FONT, self.FONT_SCALE_MEDIUM, 1)

        x = w - tw - 30
        y = h - 50

        cv2.rectangle(frame, (x - 10, y - th - 10), (x + tw + 10, y + 10), (0, 200, 0), -1)
        cv2.putText(
            frame,
            text,
            (x, y),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            (0, 0, 0),
            1,
        )

        return frame

    def draw_keypoints(
        self,
        frame: np.ndarray,
        body_points,
        pose_state: PatientPoseState,
        bed_bbox: Tuple[int, int, int, int],
    ) -> np.ndarray:
        """
        Desenha keypoints monitorados no frame.

        Args:
            frame: Frame de video.
            body_points: BodyPoints com pontos do corpo.
            pose_state: Estado atual de pose do paciente.
            bed_bbox: Bbox da cama para determinar cor.

        Returns:
            Frame com keypoints desenhados.
        """
        # Cores baseadas no estado
        state_color = StateMachine.get_pose_state_color(pose_state)

        # Cor verde para dentro da cama, laranja para fora
        COLOR_IN_BED = (0, 255, 0)     # Verde
        COLOR_OUT_BED = (0, 165, 255)  # Laranja
        COLOR_LOW_CONF = (128, 128, 128)  # Cinza para baixa confianca

        def is_in_bed(point):
            if point is None:
                return None
            x1, y1, x2, y2 = bed_bbox
            px, py = point
            margin = 0.1
            bed_width = x2 - x1
            bed_height = y2 - y1
            x1_exp = x1 - bed_width * margin
            x2_exp = x2 + bed_width * margin
            y1_exp = y1 - bed_height * margin
            y2_exp = y2 + bed_height * margin
            return x1_exp <= px <= x2_exp and y1_exp <= py <= y2_exp

        def draw_point(point, conf, name):
            if point is None:
                return
            px, py = int(point[0]), int(point[1])

            # Determina cor baseada em confianca e posicao
            if conf < POSE_CONFIDENCE_HIGH:
                color = COLOR_LOW_CONF
                radius = 5
            elif is_in_bed(point):
                color = COLOR_IN_BED
                radius = 8
            else:
                color = COLOR_OUT_BED
                radius = 8

            # Desenha circulo
            cv2.circle(frame, (px, py), radius, color, -1)
            cv2.circle(frame, (px, py), radius, (0, 0, 0), 1)

            # Label pequeno
            label = name[:3].upper()
            cv2.putText(
                frame,
                label,
                (px + 10, py + 5),
                self.FONT,
                0.4,
                color,
                1,
            )

        # Desenha cada ponto
        if body_points.neck:
            draw_point(body_points.neck, body_points.neck_conf, "NEC")
        if body_points.left_shoulder:
            draw_point(body_points.left_shoulder, body_points.left_shoulder_conf, "LSH")
        if body_points.right_shoulder:
            draw_point(body_points.right_shoulder, body_points.right_shoulder_conf, "RSH")
        if body_points.hip_center:
            draw_point(body_points.hip_center, body_points.hip_conf, "HIP")
        if body_points.left_knee:
            draw_point(body_points.left_knee, body_points.left_knee_conf, "LKN")
        if body_points.right_knee:
            draw_point(body_points.right_knee, body_points.right_knee_conf, "RKN")
        if body_points.left_ankle:
            draw_point(body_points.left_ankle, body_points.left_ankle_conf, "LAN")
        if body_points.right_ankle:
            draw_point(body_points.right_ankle, body_points.right_ankle_conf, "RAN")

        # Desenha linhas conectando pontos principais (esqueleto simplificado)
        if body_points.neck and body_points.hip_center:
            if body_points.neck_conf >= POSE_CONFIDENCE_HIGH and body_points.hip_conf >= POSE_CONFIDENCE_HIGH:
                pt1 = (int(body_points.neck[0]), int(body_points.neck[1]))
                pt2 = (int(body_points.hip_center[0]), int(body_points.hip_center[1]))
                cv2.line(frame, pt1, pt2, state_color, 2)

        return frame

    def draw_pose_state_message(
        self,
        frame: np.ndarray,
        pose_state: PatientPoseState,
    ) -> np.ndarray:
        """
        Desenha mensagem de estado do paciente baseado em pose.

        Args:
            frame: Frame de video.
            pose_state: Estado atual de pose do paciente.

        Returns:
            Frame com mensagem de estado.
        """
        messages = {
            PatientPoseState.AGUARDANDO: "Aguardando paciente...",
            PatientPoseState.MONITORANDO: "Paciente em monitoramento",
            PatientPoseState.RISCO_POTENCIAL: "ATENCAO: Risco de queda",
            PatientPoseState.PACIENTE_FORA: "ALERTA: Paciente fora da cama!",
            PatientPoseState.ACOMPANHADO: "Paciente acompanhado",
        }

        colors = StateMachine.POSE_STATE_COLORS

        message = messages.get(pose_state, "Estado desconhecido")
        color = colors.get(pose_state, (255, 255, 255))

        h, w = frame.shape[:2]

        # Posicao da mensagem (parte inferior central)
        (tw, th), _ = cv2.getTextSize(message, self.FONT, self.FONT_SCALE_LARGE, 2)
        x = (w - tw) // 2
        y = h - 30

        # Fundo para melhor visibilidade
        padding = 10
        cv2.rectangle(
            frame,
            (x - padding, y - th - padding),
            (x + tw + padding, y + padding),
            (0, 0, 0),
            -1,
        )

        # Borda colorida
        cv2.rectangle(
            frame,
            (x - padding, y - th - padding),
            (x + tw + padding, y + padding),
            color,
            2,
        )

        # Texto
        cv2.putText(
            frame,
            message,
            (x, y),
            self.FONT,
            self.FONT_SCALE_LARGE,
            color,
            2,
        )

        return frame

    def draw_pose_dashboard(
        self,
        frame: np.ndarray,
        body_points,
        pose_state: PatientPoseState,
        analysis,
    ) -> np.ndarray:
        """
        Desenha painel lateral com metricas de pose.

        Args:
            frame: Frame de video.
            body_points: BodyPoints com pontos do corpo.
            pose_state: Estado atual de pose.
            analysis: PositionAnalysis com resultado da analise.

        Returns:
            Frame com dashboard de pose.
        """
        h, w = frame.shape[:2]

        # Cria painel lateral
        dashboard = np.full((h, self.dashboard_width, 3), self.COLOR_DASHBOARD_BG, dtype=np.uint8)

        # Titulo
        cv2.putText(
            dashboard,
            "POSE MONITOR",
            (10, 30),
            self.FONT,
            self.FONT_SCALE_MEDIUM,
            self.COLOR_TEXT,
            1,
        )
        cv2.line(dashboard, (10, 40), (self.dashboard_width - 10, 40), self.COLOR_TEXT, 1)

        # Estado atual
        state_color = StateMachine.get_pose_state_color(pose_state)
        cv2.putText(
            dashboard,
            f"Estado:",
            (10, 65),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )
        cv2.putText(
            dashboard,
            f"{pose_state.value}",
            (10, 85),
            self.FONT,
            self.FONT_SCALE_SMALL,
            state_color,
            1,
        )

        # Modo ocluso
        if analysis and analysis.occluded_mode:
            cv2.putText(
                dashboard,
                "MODO OCLUSO",
                (10, 100),
                self.FONT,
                self.FONT_SCALE_SMALL,
                (0, 255, 255),  # Amarelo
                1,
            )

        # Calcula posição do separador
        y_sep = 115 if (analysis and analysis.occluded_mode) else 100

        # Postura detectada
        if analysis and analysis.is_standing is not None:
            if analysis.is_standing:
                posture_text = "PASSANTE"
                posture_color = (0, 0, 255)    # Vermelho
            else:
                posture_text = "PACIENTE"
                posture_color = (0, 255, 0)    # Verde
            detail = ""
            if analysis.person_bbox_aspect_ratio is not None:
                detail += f" AR:{analysis.person_bbox_aspect_ratio:.1f}"
            if analysis.person_bed_overlap is not None:
                detail += f" OV:{analysis.person_bed_overlap:.0%}"
            cv2.putText(dashboard, posture_text + detail, (10, y_sep),
                        self.FONT, self.FONT_SCALE_SMALL, posture_color, 1)
            y_sep += 15

        # Postura sentada (ângulo)
        if analysis and analysis.torso_hip_knee_angle is not None:
            angle_val = analysis.torso_hip_knee_angle
            if analysis.is_sitting:
                sit_text = f"SENTADO {angle_val:.0f}deg"
                sit_color = (0, 165, 255)   # Laranja
            else:
                sit_text = f"Angulo: {angle_val:.0f}deg"
                sit_color = (0, 255, 0)     # Verde
            cv2.putText(dashboard, sit_text, (10, y_sep),
                        self.FONT, self.FONT_SCALE_SMALL, sit_color, 1)
            y_sep += 15

        # Separador
        cv2.line(dashboard, (10, y_sep), (self.dashboard_width - 10, y_sep), self.COLOR_TEXT, 1)

        # Pontos do corpo
        y_pos = y_sep + 25
        cv2.putText(
            dashboard,
            "Keypoints:",
            (10, y_pos),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )
        y_pos += 25

        if body_points:
            points_info = [
                ("Pescoco", body_points.neck_conf, analysis.neck_in_bed if analysis else None),
                ("Ombro E", body_points.left_shoulder_conf, analysis.left_shoulder_in_bed if analysis else None),
                ("Ombro D", body_points.right_shoulder_conf, analysis.right_shoulder_in_bed if analysis else None),
                ("Quadris", body_points.hip_conf, analysis.hip_in_bed if analysis else None),
                ("Joelho E", body_points.left_knee_conf, analysis.left_knee_in_bed if analysis else None),
                ("Joelho D", body_points.right_knee_conf, analysis.right_knee_in_bed if analysis else None),
                ("Tornoz E", body_points.left_ankle_conf, analysis.left_ankle_in_bed if analysis else None),
                ("Tornoz D", body_points.right_ankle_conf, analysis.right_ankle_in_bed if analysis else None),
            ]

            for name, conf, in_bed in points_info:
                # Cor baseada em status
                if conf < 0.3:
                    status = "---"
                    color = (128, 128, 128)
                elif in_bed is None:
                    status = f"{conf:.1f}"
                    color = (128, 128, 128)
                elif in_bed:
                    status = "OK"
                    color = (0, 255, 0)
                else:
                    status = "FORA"
                    color = (0, 165, 255)

                text = f"{name}: {status}"
                cv2.putText(
                    dashboard,
                    text,
                    (10, y_pos),
                    self.FONT,
                    0.4,
                    color,
                    1,
                )
                y_pos += 20
        else:
            cv2.putText(
                dashboard,
                "Sem deteccao",
                (10, y_pos),
                self.FONT,
                self.FONT_SCALE_SMALL,
                (128, 128, 128),
                1,
            )

        # Separador
        y_pos += 10
        cv2.line(dashboard, (10, y_pos), (self.dashboard_width - 10, y_pos), self.COLOR_TEXT, 1)
        y_pos += 25

        # Resumo da analise
        if analysis:
            cv2.putText(
                dashboard,
                f"Pontos: {analysis.points_monitored}",
                (10, y_pos),
                self.FONT,
                self.FONT_SCALE_SMALL,
                self.COLOR_TEXT,
                1,
            )
            y_pos += 20

            cv2.putText(
                dashboard,
                f"Dentro: {analysis.points_inside}",
                (10, y_pos),
                self.FONT,
                self.FONT_SCALE_SMALL,
                (0, 255, 0),
                1,
            )
            y_pos += 20

            cv2.putText(
                dashboard,
                f"Fora: {analysis.points_outside}",
                (10, y_pos),
                self.FONT,
                self.FONT_SCALE_SMALL,
                (0, 165, 255) if analysis.points_outside > 0 else self.COLOR_TEXT,
                1,
            )

        # Controles no final
        y_pos = h - 60
        cv2.line(dashboard, (10, y_pos - 10), (self.dashboard_width - 10, y_pos - 10), self.COLOR_TEXT, 1)
        cv2.putText(
            dashboard,
            "CONTROLES",
            (10, y_pos + 10),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )

        controls = ["[Q] Sair", "[R] Reset"]
        for i, ctrl in enumerate(controls):
            cv2.putText(
                dashboard,
                ctrl,
                (10, y_pos + 30 + i * 15),
                self.FONT,
                0.4,
                (200, 200, 200),
                1,
            )

        # Concatena dashboard ao frame
        return np.hstack([frame, dashboard])

    def draw_ema_scores(
        self,
        frame: np.ndarray,
        scores: dict,
    ) -> np.ndarray:
        """
        Desenha scores EMA no canto do frame para debug.

        Args:
            frame: Frame de video (com dashboard ja adicionado).
            scores: Dict com scores EMA.

        Returns:
            Frame com scores.
        """
        h, w = frame.shape[:2]

        # Posicao no canto superior direito do video (antes do dashboard)
        # O dashboard tem largura DASHBOARD_WIDTH, entao o video termina em w - DASHBOARD_WIDTH
        video_width = w - self.dashboard_width
        x = video_width - 170
        y = 50

        # Verifica se posicao eh valida
        if x < 10:
            x = 10

        # Fundo semi-transparente
        overlay = frame.copy()
        cv2.rectangle(overlay, (x - 10, y - 20), (x + 160, y + 95), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)

        # Titulo
        cv2.putText(
            frame,
            "EMA Scores",
            (x, y),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )

        # Scores com barras visuais
        score_items = [
            ("Visiv", scores.get("visible", 0), (255, 255, 255)),
            ("Safe", scores.get("safe", 0), (0, 255, 0)),
            ("Risk", scores.get("risk", 0), (0, 165, 255)),
            ("Out", scores.get("out", 0), (0, 0, 255)),
        ]

        bar_width = 80
        for i, (name, score, color) in enumerate(score_items):
            y_item = y + 20 + i * 18

            # Nome e valor
            cv2.putText(
                frame,
                f"{name}:",
                (x, y_item),
                self.FONT,
                0.4,
                self.COLOR_TEXT,
                1,
            )

            # Barra de progresso
            bar_x = x + 40
            bar_fill = int(score * bar_width)
            cv2.rectangle(frame, (bar_x, y_item - 10), (bar_x + bar_width, y_item), (60, 60, 60), -1)
            cv2.rectangle(frame, (bar_x, y_item - 10), (bar_x + bar_fill, y_item), color, -1)

            # Valor
            cv2.putText(
                frame,
                f"{score:.2f}",
                (bar_x + bar_width + 5, y_item),
                self.FONT,
                0.4,
                color,
                1,
            )

        return frame

        # Controles no final
        y_pos = h - 60
        cv2.line(dashboard, (10, y_pos - 10), (self.dashboard_width - 10, y_pos - 10), self.COLOR_TEXT, 1)
        cv2.putText(
            dashboard,
            "CONTROLES",
            (10, y_pos + 10),
            self.FONT,
            self.FONT_SCALE_SMALL,
            self.COLOR_TEXT,
            1,
        )

        controls = ["[Q] Sair", "[R] Reset"]
        for i, ctrl in enumerate(controls):
            cv2.putText(
                dashboard,
                ctrl,
                (10, y_pos + 30 + i * 15),
                self.FONT,
                0.4,
                (200, 200, 200),
                1,
            )

        # Concatena dashboard ao frame
        return np.hstack([frame, dashboard])

    def _get_pose_state_color_bgr(self, state: PatientPoseState) -> Tuple[int, int, int]:
        """Retorna cor BGR para o estado de pose."""
        return StateMachine.get_pose_state_color(state)

    def render(self, frame: np.ndarray) -> int:
        """
        Exibe frame na janela e retorna tecla pressionada.

        No modo headless, apenas aguarda um pequeno delay e retorna -1.
        Isso evita consumo excessivo de CPU.

        Args:
            frame: Frame final para exibição.

        Returns:
            Código da tecla pressionada (ou -1 se nenhuma).
        """
        self._display.show(self.window_name, frame)
        return self._display.wait_key(1)

    def should_draw(self) -> bool:
        """
        Verifica se deve realizar operações de desenho.

        No modo headless, retorna False para economizar CPU.
        Útil para pular operações de desenho complexas que não são
        necessárias quando não há display.

        Returns:
            True se deve desenhar, False se pode pular.
        """
        return not self.skip_rendering

    def close(self) -> None:
        """Fecha a janela de exibição."""
        self._display.destroy_all()

    def _get_state_color_bgr(self, state: PatientState) -> Tuple[int, int, int]:
        """Retorna cor BGR para o estado."""
        colors = {
            PatientState.VAZIO: (128, 128, 128),
            PatientState.REPOUSO: (0, 255, 0),
            PatientState.ALERTA: (0, 255, 255),
            PatientState.CRITICO: (0, 0, 255),
        }
        return colors.get(state, (255, 255, 255))
