#!/bin/bash
# =============================================================================
# Configura o Raspberry Pi para ter display virtual sempre disponível
# =============================================================================
#
# Este script garante que o X11 esteja sempre ativo, mesmo sem monitor físico.
# Isso permite que:
# - O sistema inicie normalmente sem monitor
# - Um técnico possa conectar um monitor HDMI a qualquer momento
# - A GUI do OpenCV funcione sempre
#
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================================================="
echo "     CONFIGURAÇÃO DE DISPLAY VIRTUAL - RASPBERRY PI"
echo "============================================================================="

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERRO: Execute como root (sudo bash setup-display.sh)${NC}"
    exit 1
fi

# Detecta arquivo de config do boot
BOOT_CONFIG="/boot/config.txt"
if [ -f "/boot/firmware/config.txt" ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
fi

echo ""
echo -e "${YELLOW}[1/3] Configurando HDMI para funcionar sem monitor...${NC}"

# Backup do config.txt
cp "$BOOT_CONFIG" "${BOOT_CONFIG}.backup.$(date +%Y%m%d%H%M%S)"

# Configura HDMI hotplug (funciona mesmo sem monitor conectado no boot)
if ! grep -q "hdmi_force_hotplug=1" "$BOOT_CONFIG"; then
    echo "" >> "$BOOT_CONFIG"
    echo "# MVision: Força HDMI ativo mesmo sem monitor" >> "$BOOT_CONFIG"
    echo "hdmi_force_hotplug=1" >> "$BOOT_CONFIG"
    echo -e "${GREEN}Adicionado hdmi_force_hotplug=1${NC}"
else
    echo "hdmi_force_hotplug já configurado"
fi

# Define um modo de vídeo padrão (720p)
if ! grep -q "hdmi_group=1" "$BOOT_CONFIG"; then
    echo "hdmi_group=1" >> "$BOOT_CONFIG"
    echo "hdmi_mode=4" >> "$BOOT_CONFIG"
    echo -e "${GREEN}Configurado modo HDMI padrão (720p)${NC}"
else
    echo "Modo HDMI já configurado"
fi

echo ""
echo -e "${YELLOW}[2/3] Verificando configuração do desktop...${NC}"

# Verifica se o desktop está habilitado
if systemctl is-enabled lightdm &>/dev/null || systemctl is-enabled gdm &>/dev/null; then
    echo -e "${GREEN}Desktop manager está habilitado${NC}"
else
    echo -e "${YELLOW}Habilitando boot em modo desktop...${NC}"
    # Configura boot para desktop com autologin
    raspi-config nonint do_boot_behaviour B4 2>/dev/null || {
        echo -e "${YELLOW}Não foi possível configurar automaticamente.${NC}"
        echo "Execute manualmente: sudo raspi-config -> System Options -> Boot -> Desktop Autologin"
    }
fi

echo ""
echo -e "${YELLOW}[3/3] Configurando variáveis de ambiente para o serviço...${NC}"

# Garante que o serviço tem as variáveis de display corretas
SERVICE_FILE="/etc/systemd/system/hospital-monitor.service"
if [ -f "$SERVICE_FILE" ]; then
    # Verifica se DISPLAY está configurado
    if grep -q "DISPLAY=:0" "$SERVICE_FILE"; then
        echo -e "${GREEN}Variável DISPLAY já configurada no serviço${NC}"
    else
        echo -e "${YELLOW}Adicionando DISPLAY=:0 ao serviço...${NC}"
        sed -i '/Environment=PYTHONUNBUFFERED=1/a Environment=DISPLAY=:0\nEnvironment=XAUTHORITY=/home/tmed/.Xauthority' "$SERVICE_FILE"
        systemctl daemon-reload
    fi
fi

echo ""
echo "============================================================================="
echo -e "${GREEN}CONFIGURAÇÃO CONCLUÍDA${NC}"
echo "============================================================================="
echo ""
echo "O que foi configurado:"
echo "  ✓ HDMI força hotplug (funciona sem monitor no boot)"
echo "  ✓ Modo de vídeo padrão 720p"
echo "  ✓ Desktop habilitado para X11 sempre ativo"
echo ""
echo -e "${YELLOW}IMPORTANTE: Reinicie o Raspberry Pi para aplicar as mudanças:${NC}"
echo "  sudo reboot"
echo ""
echo "Após reiniciar:"
echo "  - O sistema iniciará normalmente mesmo sem monitor"
echo "  - Conectar um monitor HDMI mostrará a interface"
echo "  - A GUI do MVision estará sempre renderizando"
echo ""
echo "============================================================================="
