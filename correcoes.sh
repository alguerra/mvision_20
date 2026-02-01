#!/bin/bash
# =============================================================================
# Script de Correções - MVision Monitor
# =============================================================================
# Este script aplica correções para problemas comuns:
# 1. Reinicializações do sistema
# 2. Interface web inacessível
# =============================================================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "============================================================================="
echo "                    CORREÇÕES MVISION MONITOR"
echo "============================================================================="
echo "Data/Hora: $(date)"
echo "============================================================================="

# Verifica se está rodando como root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERRO: Este script precisa ser executado como root (sudo)${NC}"
    exit 1
fi

# Menu de opções
show_menu() {
    echo ""
    echo -e "${BLUE}Selecione a correção a aplicar:${NC}"
    echo ""
    echo "1) Reiniciar serviço de monitoramento (hospital-monitor)"
    echo "2) Reiniciar interface web (mvision-web)"
    echo "3) Reiniciar ambos os serviços"
    echo "4) Atualizar heartbeat manualmente"
    echo "5) Limpar memória (drop caches)"
    echo "6) Verificar e corrigir permissões"
    echo "7) Desabilitar watchdog temporariamente (CUIDADO)"
    echo "8) Restaurar watchdog"
    echo "9) Ver todos os logs em tempo real"
    echo "0) Sair"
    echo ""
}

# Função 1: Reiniciar hospital-monitor
restart_monitor() {
    echo -e "${YELLOW}► Reiniciando hospital-monitor...${NC}"
    systemctl restart hospital-monitor
    sleep 2
    systemctl status hospital-monitor --no-pager
    echo -e "${GREEN}✓ Serviço reiniciado${NC}"
}

# Função 2: Reiniciar mvision-web
restart_web() {
    echo -e "${YELLOW}► Reiniciando mvision-web...${NC}"
    systemctl restart mvision-web
    sleep 2
    systemctl status mvision-web --no-pager
    echo -e "${GREEN}✓ Serviço reiniciado${NC}"

    # Mostrar URL de acesso
    IP=$(hostname -I | awk '{print $1}')
    echo ""
    echo -e "${GREEN}Interface web disponível em: http://${IP}:8080${NC}"
    echo "Senha padrão: mvision123"
}

# Função 3: Reiniciar ambos
restart_both() {
    restart_monitor
    echo ""
    restart_web
}

# Função 4: Atualizar heartbeat
update_heartbeat() {
    echo -e "${YELLOW}► Atualizando heartbeat manualmente...${NC}"
    HEARTBEAT_FILE="/tmp/hospital-monitor-heartbeat"
    echo "$(date +%s)" > "$HEARTBEAT_FILE"
    chmod 644 "$HEARTBEAT_FILE"
    echo -e "${GREEN}✓ Heartbeat atualizado: $(cat $HEARTBEAT_FILE)${NC}"
    echo "Isso dá mais 90 segundos antes do watchdog agir"
}

# Função 5: Limpar memória
clear_memory() {
    echo -e "${YELLOW}► Limpando caches de memória...${NC}"
    echo "Memória antes:"
    free -h
    echo ""
    sync
    echo 3 > /proc/sys/vm/drop_caches
    echo "Memória depois:"
    free -h
    echo -e "${GREEN}✓ Caches limpos${NC}"
}

# Função 6: Corrigir permissões
fix_permissions() {
    echo -e "${YELLOW}► Verificando e corrigindo permissões...${NC}"

    # Diretório do projeto
    PROJECT_DIR="/home/tmed/MVC_20"
    if [ -d "$PROJECT_DIR" ]; then
        chown -R tmed:tmed "$PROJECT_DIR"
        chmod -R 755 "$PROJECT_DIR"
        echo "✓ Permissões de $PROJECT_DIR corrigidas"
    fi

    # Arquivo de heartbeat
    HEARTBEAT_FILE="/tmp/hospital-monitor-heartbeat"
    if [ -f "$HEARTBEAT_FILE" ]; then
        chmod 644 "$HEARTBEAT_FILE"
        echo "✓ Permissões do heartbeat corrigidas"
    fi

    # Diretório de logs
    LOG_DIR="/var/log/mvision"
    if [ -d "$LOG_DIR" ]; then
        chown -R tmed:tmed "$LOG_DIR"
        chmod -R 755 "$LOG_DIR"
        echo "✓ Permissões de $LOG_DIR corrigidas"
    fi

    echo -e "${GREEN}✓ Permissões verificadas${NC}"
}

# Função 7: Desabilitar watchdog temporariamente
disable_watchdog() {
    echo -e "${RED}ATENÇÃO: Desabilitar o watchdog pode deixar o sistema sem proteção!${NC}"
    read -p "Tem certeza? (s/N): " confirm
    if [ "$confirm" = "s" ] || [ "$confirm" = "S" ]; then
        echo -e "${YELLOW}► Desabilitando watchdog...${NC}"
        systemctl stop watchdog 2>/dev/null || true
        echo -e "${YELLOW}Watchdog desabilitado. Lembre-se de reabilitar!${NC}"
    else
        echo "Operação cancelada"
    fi
}

# Função 8: Restaurar watchdog
enable_watchdog() {
    echo -e "${YELLOW}► Habilitando watchdog...${NC}"
    systemctl start watchdog 2>/dev/null || true
    systemctl status watchdog --no-pager 2>/dev/null || echo "Watchdog pode não estar instalado"
    echo -e "${GREEN}✓ Watchdog habilitado${NC}"
}

# Função 9: Ver logs em tempo real
view_logs() {
    echo -e "${YELLOW}► Mostrando logs em tempo real (Ctrl+C para sair)...${NC}"
    echo "Combinando logs de hospital-monitor e mvision-web"
    echo ""
    journalctl -u hospital-monitor -u mvision-web -f
}

# Loop principal
while true; do
    show_menu
    read -p "Opção: " choice

    case $choice in
        1) restart_monitor ;;
        2) restart_web ;;
        3) restart_both ;;
        4) update_heartbeat ;;
        5) clear_memory ;;
        6) fix_permissions ;;
        7) disable_watchdog ;;
        8) enable_watchdog ;;
        9) view_logs ;;
        0)
            echo "Saindo..."
            exit 0
            ;;
        *)
            echo -e "${RED}Opção inválida${NC}"
            ;;
    esac

    echo ""
    read -p "Pressione Enter para continuar..."
done
