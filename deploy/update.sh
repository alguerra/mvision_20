#!/bin/bash
# =============================================================================
# Script para aplicar atualizações do código (uso em laboratório)
# =============================================================================
#
# USO (após modificar/sincronizar o código):
#   sudo bash deploy/update.sh
#
# O QUE FAZ:
#   - Reinicia AMBOS os serviços (monitor E painel web)
#   - Roda o diagnóstico (mvision-doctor) para confirmar que tudo subiu
#
# Para atualização em campo SEM rede, use o pendrive (ver usb-update.sh).
# =============================================================================

echo "=============================================="
echo "Aplicando atualizações..."
echo "=============================================="

if [ "$EUID" -ne 0 ]; then
    echo "ERRO: Execute como root: sudo bash update.sh"
    exit 1
fi

echo ""
echo "Reiniciando serviços (monitor + painel web)..."
systemctl restart mvision-web
systemctl restart hospital-monitor

echo "Aguardando serviços subirem..."
sleep 8

if command -v mvision-doctor &>/dev/null; then
    mvision-doctor
else
    systemctl status hospital-monitor --no-pager | head -5
    systemctl status mvision-web --no-pager | head -5
    echo "(mvision-doctor nao instalado - rode: sudo bash deploy/install.sh)"
fi
