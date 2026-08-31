#!/bin/bash
# =============================================================================
# mvision-usb-update — Atualização OFFLINE via pendrive
# =============================================================================
#
# Roda no boot (mvision-usb-update.service), ANTES do monitor subir.
# Procura em qualquer particao USB um pacote:
#     mvision-update-<versao>.tar.gz
#     mvision-update-<versao>.tar.gz.sha256
#
# Se o checksum confere e a versao ainda nao foi aplicada, extrai sobre o
# diretorio do projeto, roda o instalador e registra em /var/log.
#
# PROCEDIMENTO DO TECNICO: desligar da tomada -> espetar o pendrive ->
# ligar -> aguardar o painel voltar -> conferir versao no mvision-doctor ->
# remover o pendrive.
#
# Como gerar o pacote (no laboratorio):
#   git archive --format=tar.gz -o mvision-update-<versao>.tar.gz HEAD
#   (adicionar os .pt reais se mudaram: tar --append nao funciona em .gz;
#    gere com: tar czf ... --exclude-vcs -C /caminho/do/projeto .)
#   sha256sum mvision-update-<versao>.tar.gz > mvision-update-<versao>.tar.gz.sha256
# =============================================================================

LOG=/var/log/mvision-usb-update.log
MOUNT_POINT=/mnt/mvision-usb
APPLIED_DIR=/var/lib/mvision-updates

exec >>"$LOG" 2>&1
echo "=== mvision-usb-update $(date '+%Y-%m-%d %H:%M:%S') ==="

UNIT_DIR=$(grep -oP '^WorkingDirectory=\K.*' /etc/systemd/system/hospital-monitor.service 2>/dev/null)
PROJECT_DIR="${UNIT_DIR:-/mvision}"
mkdir -p "$APPLIED_DIR" "$MOUNT_POINT"

# --- Ciclo do overlay (protecao do SD) ---------------------------------------
# Com o overlay ativo, extrair a atualizacao seria inutil (iria para a RAM).
# O ciclo e: detectar pacote novo -> desligar overlay + marcador -> reboot ->
# aplicar de verdade -> religar overlay -> reboot. O marcador mora em local
# PERSISTENTE (particao de dados ou boot), nunca sob o overlay.
overlay_active() { [ "$(findmnt -no FSTYPE / 2>/dev/null)" = "overlay" ]; }
if findmnt -no TARGET /mvision-data &>/dev/null; then
    REENABLE_MARKER=/mvision-data/.mvision-reenable-overlay
else
    BOOT_DIR="/boot/firmware"; [ -d "$BOOT_DIR" ] || BOOT_DIR="/boot"
    REENABLE_MARKER="$BOOT_DIR/mvision-reenable-overlay"
fi

cleanup() { umount "$MOUNT_POINT" 2>/dev/null; }
trap cleanup EXIT

# Procura pacote em todas as particoes USB
for dev in /dev/sd[a-z][0-9]*; do
    [ -b "$dev" ] || continue
    echo "Verificando $dev..."
    umount "$MOUNT_POINT" 2>/dev/null
    mount -o ro "$dev" "$MOUNT_POINT" 2>/dev/null || continue

    PKG=$(ls "$MOUNT_POINT"/mvision-update-*.tar.gz 2>/dev/null | sort | tail -1)
    if [ -z "$PKG" ]; then
        echo "  Sem pacote de atualizacao em $dev"
        continue
    fi

    PKG_NAME=$(basename "$PKG")
    echo "  Pacote encontrado: $PKG_NAME"

    # Ja aplicado? (idempotente: pendrive esquecido nao re-aplica a cada boot)
    if [ -f "$APPLIED_DIR/$PKG_NAME.applied" ]; then
        echo "  Ja aplicado anteriormente - ignorando"
        continue
    fi

    # Verifica integridade
    if [ ! -f "$PKG.sha256" ]; then
        echo "  ERRO: $PKG_NAME.sha256 ausente - pacote recusado"
        continue
    fi
    EXPECTED=$(awk '{print $1}' "$PKG.sha256")
    ACTUAL=$(sha256sum "$PKG" | awk '{print $1}')
    if [ "$EXPECTED" != "$ACTUAL" ]; then
        echo "  ERRO: checksum NAO confere - pacote corrompido, recusado"
        continue
    fi
    echo "  Checksum OK"

    # Overlay ativo? Nao da para aplicar neste boot: desliga e reinicia.
    if overlay_active; then
        if [ -f "$REENABLE_MARKER" ]; then
            echo "  ERRO: overlay continua ativo apos tentativa de desativacao anterior."
            echo "  Intervencao manual: sudo mvision-overlay --disable && sudo reboot"
            exit 1
        fi
        echo "  Overlay ativo - desativando para aplicar a atualizacao no proximo boot..."
        if raspi-config nonint disable_overlayfs; then
            touch "$REENABLE_MARKER"
            echo "  Reiniciando em 5s (a atualizacao sera aplicada no proximo boot)"
            ( sleep 5; reboot ) &
            exit 0
        else
            echo "  ERRO: falha ao desativar o overlay - atualizacao adiada"
            exit 1
        fi
    fi

    # Aplica: backup leve do codigo atual + extracao
    echo "  Parando servicos..."
    systemctl stop hospital-monitor mvision-web 2>/dev/null

    BACKUP="/var/lib/mvision-updates/backup-$(date +%Y%m%d%H%M%S).tar.gz"
    echo "  Backup do codigo atual em $BACKUP..."
    tar czf "$BACKUP" --exclude='data' --exclude='.git' --exclude='*.pt' -C "$PROJECT_DIR" . 2>/dev/null
    # Mantem apenas os 2 backups mais recentes
    ls -t /var/lib/mvision-updates/backup-*.tar.gz 2>/dev/null | tail -n +3 | xargs -r rm -f

    echo "  Extraindo atualizacao..."
    if tar xzf "$PKG" -C "$PROJECT_DIR"; then
        touch "$APPLIED_DIR/$PKG_NAME.applied"
        echo "  Extraido com sucesso - rodando instalador..."
        bash "$PROJECT_DIR/deploy/install.sh" && echo "  ATUALIZACAO $PKG_NAME APLICADA" \
            || echo "  AVISO: instalador reportou problemas (ver acima)"
        # Se este boot veio do ciclo do overlay, religa a protecao do SD
        if [ -f "$REENABLE_MARKER" ]; then
            rm -f "$REENABLE_MARKER"
            echo "  Religando protecao do SD (overlay)..."
            if command -v mvision-overlay >/dev/null && mvision-overlay --enable; then
                echo "  Overlay religado - reiniciando em 5s"
                ( sleep 5; reboot ) &
            else
                echo "  AVISO: falha ao religar o overlay - religue manualmente (mvision-overlay --enable)"
            fi
        fi
    else
        echo "  ERRO na extracao - restaurando backup..."
        tar xzf "$BACKUP" -C "$PROJECT_DIR"
        systemctl start mvision-web hospital-monitor
    fi
    exit 0
done

echo "Nenhuma atualizacao USB encontrada - boot normal"
exit 0
