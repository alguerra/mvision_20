#!/bin/bash
# Script para configurar watchdog de hardware no Raspberry Pi
# Executar como root: sudo bash setup-watchdog.sh
#
# O watchdog de hardware reinicia o Raspberry Pi automaticamente se:
# - O sistema travar completamente
# - O arquivo de heartbeat não for atualizado
# - A carga do sistema for muito alta

set -e

echo "=== Configurando Watchdog do Raspberry Pi ==="

# Verifica se está rodando como root
if [ "$EUID" -ne 0 ]; then
    echo "ERRO: Execute como root (sudo bash setup-watchdog.sh)"
    exit 1
fi

# 1. Habilita watchdog no boot (Raspberry Pi 4/5)
echo "[1/5] Habilitando watchdog no boot..."
BOOT_CONFIG="/boot/config.txt"
# No Raspberry Pi OS mais recente, pode ser /boot/firmware/config.txt
if [ -f "/boot/firmware/config.txt" ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
fi

if ! grep -q "dtparam=watchdog=on" "$BOOT_CONFIG"; then
    echo "dtparam=watchdog=on" >> "$BOOT_CONFIG"
    echo "  Adicionado dtparam=watchdog=on em $BOOT_CONFIG"
else
    echo "  Watchdog ja habilitado no boot"
fi

# 2. Instala watchdog daemon
echo "[2/5] Instalando watchdog daemon..."
apt-get update -qq
apt-get install -y watchdog

# 3. Configura watchdog
echo "[3/5] Configurando /etc/watchdog.conf..."
cat > /etc/watchdog.conf << 'EOF'
# Watchdog configuration for Hospital Monitor on Raspberry Pi
# Configurado automaticamente pelo setup-watchdog.sh

# Device do watchdog de hardware
watchdog-device = /dev/watchdog

# Timeout do hardware em segundos (max 15 para RPi)
# Se o daemon nao alimentar o watchdog em 15s, o hardware reinicia
watchdog-timeout = 15

# Intervalo de verificacao do daemon (segundos)
interval = 10

# Reinicia se carga do sistema for muito alta (media de 1 minuto)
max-load-1 = 24

# Reinicia se memoria livre for muito baixa (paginas de 4KB)
min-memory = 1

# ============================================
# MONITORAMENTO DO SISTEMA HOSPITAL MONITOR
# ============================================
# Verifica se o arquivo de heartbeat foi modificado recentemente
# O main.py atualiza este arquivo a cada 30 segundos
# Se nao for atualizado em 90 segundos, o watchdog reinicia o sistema
file = /tmp/hospital-monitor-heartbeat
change = 90

# Tambem verifica se o processo Python esta rodando
pidfile = /var/run/hospital-monitor.pid

# ============================================
# LOGS
# ============================================
log-dir = /var/log/watchdog
verbose = yes
EOF

# 4. Cria diretorios necessarios
echo "[4/5] Criando diretorios..."
mkdir -p /var/log/watchdog
mkdir -p /var/log/hospital-monitor
mkdir -p /var/run

# Cria arquivo de heartbeat inicial para evitar reinicio imediato
touch /tmp/hospital-monitor-heartbeat

# 5. Habilita e inicia watchdog
echo "[5/5] Habilitando servico watchdog..."
systemctl enable watchdog
systemctl restart watchdog

# Verifica status
if systemctl is-active --quiet watchdog; then
    echo "  Watchdog daemon esta rodando"
else
    echo "  AVISO: Watchdog daemon nao iniciou corretamente"
fi

echo ""
echo "=============================================="
echo "Watchdog configurado com sucesso!"
echo "=============================================="
echo ""
echo "O sistema sera reiniciado AUTOMATICAMENTE se:"
echo "  - O arquivo /tmp/hospital-monitor-heartbeat nao for atualizado em 90s"
echo "  - O sistema operacional travar"
echo "  - A carga do sistema for muito alta"
echo "  - A memoria estiver esgotada"
echo ""
echo "IMPORTANTE: Reinicie o Raspberry Pi para ativar o watchdog de hardware:"
echo "  sudo reboot"
echo ""
echo "Apos reiniciar, verifique com:"
echo "  sudo systemctl status watchdog"
echo "  dmesg | grep watchdog"
