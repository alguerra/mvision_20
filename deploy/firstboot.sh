#!/bin/bash
# =============================================================================
# mvision-firstboot — Provisionamento do PRIMEIRO boot de uma unidade clonada
# =============================================================================
#
# Executado UMA unica vez pelo mvision-firstboot.service quando o dispositivo
# foi gravado a partir da imagem dourada (install.sh --prepare-image).
# Individualiza a unidade: chaves SSH, machine-id, expansao do filesystem.
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

# 1. Expande o filesystem para ocupar o SD inteiro (imagem clonada e menor)
echo "[1/4] Expandindo filesystem..."
raspi-config nonint do_expand_rootfs && echo "  OK (efetivo apos reboot)" || echo "  AVISO: expansao falhou (nao e Raspberry Pi OS?)"

# 2. Regenera identidade da maquina (nao pode ser clonada entre unidades)
echo "[2/4] Regenerando identidade da unidade..."
rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup
[ -f /var/lib/dbus/machine-id ] || ln -s /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null
rm -f /etc/ssh/ssh_host_*
dpkg-reconfigure -f noninteractive openssh-server 2>/dev/null || ssh-keygen -A
echo "  machine-id e chaves SSH regenerados"

# 3. Garante que segredos de aplicacao nao vieram da imagem
echo "[3/4] Limpando segredos de aplicacao..."
UNIT_DIR=$(grep -oP '^WorkingDirectory=\K.*' /etc/systemd/system/hospital-monitor.service 2>/dev/null)
PROJECT_DIR="${UNIT_DIR:-/mvision}"
rm -f "$PROJECT_DIR/config/web_auth.json"   # forca senha padrao + troca obrigatoria
echo "  OK"

# 4. Marca como concluido e agenda reboot para aplicar expansao
echo "[4/4] Finalizando..."
touch "$MARKER"
systemctl disable mvision-firstboot &>/dev/null
echo "Provisionamento concluido - reiniciando em 10s"
( sleep 10; reboot ) &
exit 0
