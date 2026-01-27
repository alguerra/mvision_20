#!/bin/bash
# Script para configurar watchdog de hardware no Raspberry Pi
# Executar como root: sudo bash setup-watchdog.sh

set -e

echo "=== Configurando Watchdog do Raspberry Pi ==="

# 1. Habilita watchdog no boot
echo "Habilitando watchdog no /boot/config.txt..."
if ! grep -q "dtparam=watchdog=on" /boot/config.txt; then
    echo "dtparam=watchdog=on" >> /boot/config.txt
    echo "  Adicionado dtparam=watchdog=on"
else
    echo "  Watchdog ja habilitado no boot"
fi

# 2. Instala watchdog daemon
echo "Instalando watchdog daemon..."
apt-get update
apt-get install -y watchdog

# 3. Configura watchdog
echo "Configurando /etc/watchdog.conf..."
cat > /etc/watchdog.conf << 'EOF'
# Watchdog configuration for Raspberry Pi

# Device do watchdog
watchdog-device = /dev/watchdog

# Timeout em segundos (max 15 para RPi)
watchdog-timeout = 15

# Intervalo de verificacao
interval = 5

# Reinicia se carga do sistema for muito alta
max-load-1 = 24

# Reinicia se memoria livre for muito baixa (paginas)
min-memory = 1

# Testa se o arquivo existe e foi modificado recentemente
# O sistema de monitoramento deve tocar este arquivo periodicamente
file = /tmp/hospital-monitor-heartbeat
change = 120

# Log
log-dir = /var/log/watchdog
verbose = yes
EOF

# 4. Cria diretorio de log
mkdir -p /var/log/watchdog
mkdir -p /var/log/hospital-monitor

# 5. Habilita e inicia watchdog
echo "Habilitando servico watchdog..."
systemctl enable watchdog
systemctl start watchdog

echo ""
echo "=== Watchdog configurado com sucesso ==="
echo "O sistema sera reiniciado automaticamente se:"
echo "  - O arquivo /tmp/hospital-monitor-heartbeat nao for atualizado em 120s"
echo "  - O sistema travar completamente"
echo "  - A carga do sistema for muito alta"
echo ""
echo "IMPORTANTE: Reinicie o Raspberry Pi para ativar o watchdog de hardware"
echo "  sudo reboot"
