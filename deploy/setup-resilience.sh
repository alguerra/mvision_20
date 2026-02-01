#!/bin/bash
# =============================================================================
# Script de Configuração de Resiliência Simplificada
# =============================================================================
#
# Este script configura uma arquitetura de resiliência mais estável:
#
# CAMADA 1: Hardware Watchdog (para freezes completos do sistema)
#   - Mantém o watchdog de hardware ativo
#   - Remove o daemon de watchdog (que causava reboots agressivos)
#   - Sistema só reinicia se o kernel travar completamente
#
# CAMADA 2: Systemd (para falhas do serviço)
#   - Restart=always garante que o serviço sempre reinicie
#   - RestartSec=10 dá tempo para liberar recursos
#   - StartLimitIntervalSec=0 remove limite de reinicializações
#
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================================================="
echo "     CONFIGURAÇÃO DE RESILIÊNCIA SIMPLIFICADA - MVISION"
echo "============================================================================="

# Verifica se está rodando como root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERRO: Execute como root (sudo bash setup-resilience.sh)${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[1/6] Parando watchdog daemon...${NC}"
systemctl stop watchdog 2>/dev/null || true
systemctl disable watchdog 2>/dev/null || true
echo -e "${GREEN}Watchdog daemon desabilitado${NC}"

echo ""
echo -e "${YELLOW}[2/6] Mantendo hardware watchdog ativo...${NC}"
# O hardware watchdog continua ativo via dtparam=watchdog=on no boot
# Mas sem o daemon, ele só atua se o kernel travar completamente
BOOT_CONFIG="/boot/config.txt"
if [ -f "/boot/firmware/config.txt" ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
fi

if grep -q "dtparam=watchdog=on" "$BOOT_CONFIG"; then
    echo -e "${GREEN}Hardware watchdog já configurado em $BOOT_CONFIG${NC}"
else
    echo "dtparam=watchdog=on" >> "$BOOT_CONFIG"
    echo -e "${GREEN}Hardware watchdog habilitado em $BOOT_CONFIG${NC}"
fi

echo ""
echo -e "${YELLOW}[3/6] Atualizando serviço hospital-monitor...${NC}"

# Atualiza o service file com configurações otimizadas
cat > /etc/systemd/system/hospital-monitor.service << 'EOF'
[Unit]
Description=Sistema de Monitoramento de Quedas Hospitalares MVision
After=network.target
Wants=network.target

# Remove limite de reinicializações - SEMPRE reinicia
StartLimitIntervalSec=0

[Service]
Type=simple
User=tmed
Group=tmed

# Diretório do código
WorkingDirectory=/mvision
ExecStart=/usr/bin/python3 -u /mvision/main.py

# SEMPRE reinicia, não importa o motivo da falha
Restart=always
RestartSec=10

# Logs
StandardOutput=journal
StandardError=journal

# Variáveis de ambiente
Environment=PYTHONUNBUFFERED=1

# Timeout generoso para inicialização (YOLO demora para carregar)
TimeoutStartSec=300
TimeoutStopSec=30

# Limites de recursos RELAXADOS (YOLO precisa de memória)
# 768MB é mais seguro para YOLOv8
MemoryMax=768M
CPUQuota=90%

# Permite acesso a GPIO e câmera
SupplementaryGroups=gpio video

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Serviço atualizado${NC}"

echo ""
echo -e "${YELLOW}[4/6] Atualizando serviço mvision-web...${NC}"

cat > /etc/systemd/system/mvision-web.service << 'EOF'
[Unit]
Description=MVision Web Configuration Interface
After=network.target
Wants=network.target

# Remove limite de reinicializações
StartLimitIntervalSec=0

[Service]
Type=simple
User=tmed
Group=tmed

WorkingDirectory=/mvision/web/backend
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8080

# SEMPRE reinicia
Restart=always
RestartSec=5

# Logs
StandardOutput=journal
StandardError=journal

Environment=PYTHONUNBUFFERED=1

# Limites de recursos (web é leve)
MemoryMax=128M
CPUQuota=20%

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Serviço web atualizado${NC}"

echo ""
echo -e "${YELLOW}[5/6] Recarregando systemd...${NC}"
systemctl daemon-reload
echo -e "${GREEN}Systemd recarregado${NC}"

echo ""
echo -e "${YELLOW}[6/6] Habilitando serviços...${NC}"
systemctl enable hospital-monitor
systemctl enable mvision-web
echo -e "${GREEN}Serviços habilitados${NC}"

echo ""
echo "============================================================================="
echo -e "${GREEN}CONFIGURAÇÃO CONCLUÍDA${NC}"
echo "============================================================================="
echo ""
echo "ARQUITETURA DE RESILIÊNCIA ATIVA:"
echo ""
echo "  CAMADA 1: Hardware Watchdog"
echo "    └─ Reinicia APENAS se o kernel travar completamente"
echo "    └─ Não monitora heartbeat (sem reboots agressivos)"
echo ""
echo "  CAMADA 2: Systemd"
echo "    └─ Restart=always em ambos os serviços"
echo "    └─ hospital-monitor: reinicia em 10s se falhar"
echo "    └─ mvision-web: reinicia em 5s se falhar"
echo "    └─ Sem limite de reinicializações"
echo ""
echo "LIMITES DE RECURSOS:"
echo "  └─ hospital-monitor: 768MB RAM, 90% CPU"
echo "  └─ mvision-web: 128MB RAM, 20% CPU"
echo ""
echo "PRÓXIMOS PASSOS:"
echo "  1. Reinicie os serviços:"
echo "     sudo systemctl restart hospital-monitor mvision-web"
echo ""
echo "  2. Ou reinicie o Raspberry Pi:"
echo "     sudo reboot"
echo ""
echo "  3. Monitore os logs:"
echo "     sudo journalctl -u hospital-monitor -f"
echo ""
echo "============================================================================="
