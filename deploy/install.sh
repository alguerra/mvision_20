#!/bin/bash
# =============================================================================
# Script de instalação do Sistema de Monitoramento no Raspberry Pi
# =============================================================================
#
# USO:
#   cd /mvision/deploy
#   sudo bash install.sh
#
# O QUE FAZ:
#   - Instala o serviço systemd (inicia automaticamente no boot)
#   - Configura permissões para câmera e GPIO
#   - NÃO copia arquivos - roda direto do diretório atual
#
# APÓS MODIFICAR O CÓDIGO:
#   sudo systemctl restart hospital-monitor
#
# =============================================================================

set -e

# Detecta o diretório do código fonte (pai do deploy/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Usuário que executa o serviço (dono do diretório do projeto)
SERVICE_USER="tmed"
SERVICE_GROUP="tmed"

echo "=============================================="
echo "Instalação do Sistema de Monitoramento"
echo "=============================================="
echo ""
echo "Diretório do projeto: $PROJECT_DIR"
echo "Usuário do serviço: $SERVICE_USER"
echo ""

# Verifica se está rodando como root
if [ "$EUID" -ne 0 ]; then
    echo "ERRO: Execute como root:"
    echo "  sudo bash install.sh"
    exit 1
fi

# Verifica se main.py existe
if [ ! -f "$PROJECT_DIR/main.py" ]; then
    echo "ERRO: main.py não encontrado em $PROJECT_DIR"
    exit 1
fi

# 1. Configura o arquivo de serviço com o caminho correto
echo "[1/4] Configurando serviço systemd..."
cat > /etc/systemd/system/hospital-monitor.service << EOF
[Unit]
Description=Sistema de Monitoramento de Quedas Hospitalares
After=graphical.target network.target
Wants=graphical.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 -u $PROJECT_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/$SERVICE_USER/.Xauthority
TimeoutStartSec=300
TimeoutStopSec=30
MemoryMax=768M
CPUQuota=90%
SupplementaryGroups=gpio video

[Install]
WantedBy=graphical.target
EOF

echo "  Serviço configurado para: $PROJECT_DIR"

# 2. Recarrega e habilita o serviço
echo "[2/4] Habilitando serviço..."
systemctl daemon-reload
systemctl enable hospital-monitor
echo "  Serviço habilitado para iniciar no boot"

# 3. Configura permissões
echo "[3/4] Configurando permissões..."
chown -R $SERVICE_USER:$SERVICE_GROUP "$PROJECT_DIR"
chmod +x "$PROJECT_DIR/main.py"

# Adiciona usuário aos grupos necessários
usermod -aG gpio $SERVICE_USER 2>/dev/null || true
usermod -aG video $SERVICE_USER 2>/dev/null || true
echo "  Usuário $SERVICE_USER adicionado aos grupos gpio e video"

# 4. Verifica arquivos importantes
echo "[4/4] Verificando configuração..."
if [ -f "$PROJECT_DIR/data/bed_reference.json" ]; then
    echo "  ✓ Referência de cama encontrada"
else
    echo "  ! Referência de cama NÃO encontrada (será calibrada no primeiro uso)"
fi

if [ -f "$PROJECT_DIR/config/environment.json" ]; then
    echo "  ✓ Configuração de ambiente encontrada"
else
    echo "  ! Configuração de ambiente NÃO encontrada"
fi

echo ""
echo "=============================================="
echo "Instalação concluída!"
echo "=============================================="
echo ""
echo "COMANDOS ÚTEIS:"
echo ""
echo "  Iniciar o serviço:"
echo "    sudo systemctl start hospital-monitor"
echo ""
echo "  Parar o serviço:"
echo "    sudo systemctl stop hospital-monitor"
echo ""
echo "  Ver status:"
echo "    sudo systemctl status hospital-monitor"
echo ""
echo "  Ver logs em tempo real:"
echo "    journalctl -u hospital-monitor -f"
echo ""
echo "  Após modificar o código, reinicie:"
echo "    sudo systemctl restart hospital-monitor"
echo ""
echo "OPCIONAL - Configurar display virtual (para funcionar sem monitor):"
echo "    sudo bash $SCRIPT_DIR/setup-display.sh"
echo ""
echo "O serviço iniciará automaticamente no próximo boot."
