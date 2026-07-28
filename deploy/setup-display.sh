#!/bin/bash
# =============================================================================
# DESCONTINUADO: a configuracao de display foi consolidada em deploy/install.sh
# (etapa [7/10], idempotente). Este atalho existe apenas para compatibilidade.
# =============================================================================
echo "[setup-display.sh] Redirecionando para o instalador consolidado..."
exec bash "$(dirname "$0")/install.sh" "$@"
