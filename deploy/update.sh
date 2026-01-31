#!/bin/bash
# =============================================================================
# Script para aplicar atualizações do código
# =============================================================================
#
# USO (após modificar o código):
#   cd /home/pi/mvision/deploy
#   sudo bash update.sh
#
# O QUE FAZ:
#   - Reinicia o serviço para aplicar as mudanças
#   - Mostra os logs para verificar se iniciou corretamente
#
# =============================================================================

echo "=============================================="
echo "Aplicando atualizações..."
echo "=============================================="

# Verifica se está rodando como root
if [ "$EUID" -ne 0 ]; then
    echo "ERRO: Execute como root:"
    echo "  sudo bash update.sh"
    exit 1
fi

# Reinicia o serviço
echo ""
echo "Reiniciando serviço..."
systemctl restart hospital-monitor

# Aguarda um pouco
sleep 3

# Mostra status
echo ""
echo "Status do serviço:"
systemctl status hospital-monitor --no-pager

echo ""
echo "=============================================="
echo "Atualização aplicada!"
echo "=============================================="
echo ""
echo "Para ver os logs em tempo real:"
echo "  journalctl -u hospital-monitor -f"
