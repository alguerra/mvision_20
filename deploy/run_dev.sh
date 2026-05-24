#!/bin/bash
# =============================================================================
# Executa o MVISION em modo desenvolvimento COM janela de vídeo
# =============================================================================
#
# USO (rodar DENTRO de uma sessão de desktop - VNC ou monitor):
#   cd /mvision/deploy
#   bash run_dev.sh
#
# Para acesso via SSH com X forwarding:
#   ssh -X tmed@raspberry
#   bash /mvision/deploy/run_dev.sh
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Detecta DISPLAY
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
    echo "[DEV] DISPLAY não definido, usando :0"
fi

# Configura XAUTHORITY se necessário
if [ -z "$XAUTHORITY" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi

echo "=============================================="
echo "  MVISION - Modo Desenvolvimento"
echo "=============================================="
echo "  Diretório: $PROJECT_DIR"
echo "  DISPLAY:   $DISPLAY"
echo "  Usuário:   $(whoami)"
echo "=============================================="

# Para o serviço systemd se estiver rodando (evita conflito de câmera)
if systemctl is-active --quiet hospital-monitor 2>/dev/null; then
    echo "[DEV] Parando serviço hospital-monitor..."
    sudo systemctl stop hospital-monitor
    sleep 2
    echo "[DEV] Serviço parado"
fi

echo "[DEV] Iniciando MVISION com vídeo..."
echo "[DEV] Pressione Q na janela ou Ctrl+C para sair"
echo ""

cd "$PROJECT_DIR"

# Roda o sistema diretamente (com saída sem buffer)
python3 -u main.py
EXIT_CODE=$?

echo ""
echo "[DEV] MVISION encerrado (código: $EXIT_CODE)"

# Pergunta se quer reiniciar o serviço
read -p "[DEV] Reiniciar serviço hospital-monitor? (s/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Ss]$ ]]; then
    echo "[DEV] Reiniciando serviço..."
    sudo systemctl start hospital-monitor
    echo "[DEV] Serviço reiniciado"
fi
