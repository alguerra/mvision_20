#!/bin/bash
# =============================================================================
# mvision-firstboot — Provisionamento do PRIMEIRO boot de uma unidade clonada
# =============================================================================
#
# Executado UMA unica vez pelo mvision-firstboot.service quando o dispositivo
# foi gravado a partir da imagem dourada (install.sh --prepare-image).
# Individualiza a unidade: expansao do filesystem (reservando a particao de
# dados persistente), chaves SSH, machine-id e — se habilitado no
# mvision-firstboot.conf da particao de boot — a protecao do SD (overlay).
# Desabilita a si mesmo ao final.
# =============================================================================

MARKER=/var/lib/mvision-firstboot-done
LOG=/var/log/mvision-firstboot.log

exec >>"$LOG" 2>&1
echo "=== mvision-firstboot $(date '+%Y-%m-%d %H:%M:%S') ==="

if [ -f "$MARKER" ]; then
    echo "Ja executado anteriormente - nada a fazer"
    systemctl disable mvision-firstboot &>/dev/null
    exit 0
fi

# Configuracao gravada na particao de boot pelo --prepare-image
BOOT_DIR="/boot/firmware"; [ -d "$BOOT_DIR" ] || BOOT_DIR="/boot"
ENABLE_OVERLAY=0
DATA_SIZE_GB=4
[ -f "$BOOT_DIR/mvision-firstboot.conf" ] && . "$BOOT_DIR/mvision-firstboot.conf"

# 1. Expande o filesystem, RESERVANDO espaco para a particao de dados
#    persistente no fim do SD (a imagem clonada e menor que o cartao).
echo "[1/6] Expandindo filesystem (reservando ${DATA_SIZE_GB}GB para dados)..."
ROOT_PART=$(findmnt -no SOURCE /)
ROOT_DEV="/dev/$(lsblk -no pkname "$ROOT_PART")"
PART_NUM=$(echo "$ROOT_PART" | grep -o '[0-9]*$')
DISK_SECTORS=$(blockdev --getsz "$ROOT_DEV" 2>/dev/null)
if [ -n "$DISK_SECTORS" ] && [ "${DATA_SIZE_GB:-0}" -gt 0 ] && command -v parted >/dev/null; then
    ROOT_END=$((DISK_SECTORS - DATA_SIZE_GB * 2097152 - 2048))
    if parted -s "$ROOT_DEV" resizepart "$PART_NUM" "${ROOT_END}s" 2>/dev/null; then
        partprobe "$ROOT_DEV" 2>/dev/null; sleep 2
        resize2fs "$ROOT_PART" && echo "  Raiz expandida ate o setor $ROOT_END"
    else
        echo "  AVISO: resize com reserva falhou - expandindo raiz no disco inteiro (sem particao de dados)"
        raspi-config nonint do_expand_rootfs
        DATA_SIZE_GB=0
    fi
else
    echo "  Sem reserva de dados (DATA_SIZE_GB=$DATA_SIZE_GB) - expansao padrao"
    raspi-config nonint do_expand_rootfs && echo "  OK (efetivo apos reboot)" || echo "  AVISO: expansao falhou (nao e Raspberry Pi OS?)"
fi

# 2. Cria a particao de dados persistente e migra data/ e config/
echo "[2/6] Particao de dados persistente..."
if [ "${DATA_SIZE_GB:-0}" -gt 0 ] && command -v mvision-overlay >/dev/null; then
    mvision-overlay --prepare-data && mvision-overlay --migrate \
        && echo "  OK" || echo "  AVISO: preparacao da particao de dados falhou (ver acima)"
else
    echo "  Pulado (sem reserva de dados ou mvision-overlay ausente)"
fi

# 3. Regenera identidade da maquina (nao pode ser clonada entre unidades)
echo "[3/6] Regenerando identidade da unidade..."
rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup
[ -f /var/lib/dbus/machine-id ] || ln -s /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null
rm -f /etc/ssh/ssh_host_*
dpkg-reconfigure -f noninteractive openssh-server 2>/dev/null || ssh-keygen -A
echo "  machine-id e chaves SSH regenerados"

# 4. Garante que segredos de aplicacao nao vieram da imagem
echo "[4/6] Limpando segredos de aplicacao..."
UNIT_DIR=$(grep -oP '^WorkingDirectory=\K.*' /etc/systemd/system/hospital-monitor.service 2>/dev/null)
PROJECT_DIR="${UNIT_DIR:-/mvision}"
rm -f "$PROJECT_DIR/config/web_auth.json"   # forca senha padrao + troca obrigatoria
echo "  OK"

# 5. Protecao do SD (overlay), se habilitada na configuracao da imagem
echo "[5/6] Protecao do SD (ENABLE_OVERLAY=$ENABLE_OVERLAY)..."
if [ "$ENABLE_OVERLAY" = "1" ] && command -v mvision-overlay >/dev/null; then
    mvision-overlay --enable && echo "  Overlay habilitado (ativo apos o reboot)" \
        || echo "  AVISO: falha ao habilitar overlay (unidade segue funcional, SEM protecao de SD)"
else
    echo "  Overlay nao habilitado (ative depois com: sudo mvision-overlay --enable)"
fi

# 6. Marca como concluido e agenda reboot para aplicar tudo
echo "[6/6] Finalizando..."
touch "$MARKER"
systemctl disable mvision-firstboot &>/dev/null
echo "Provisionamento concluido - reiniciando em 10s"
( sleep 10; reboot ) &
exit 0
