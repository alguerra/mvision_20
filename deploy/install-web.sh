#!/bin/bash
# =============================================================================
# DESCONTINUADO: a instalacao foi consolidada em deploy/install.sh
# (idempotente - instala monitor, painel web, watchdog, journald, sudoers,
#  doctor, atualizador USB e roda a verificacao final).
# Este atalho existe apenas para compatibilidade.
# =============================================================================
echo "[install-web.sh] Redirecionando para o instalador consolidado..."
exec bash "$(dirname "$0")/install.sh" "$@"
