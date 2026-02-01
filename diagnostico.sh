#!/bin/bash
# =============================================================================
# Script de Diagnóstico - MVision Monitor
# =============================================================================
# Este script coleta informações sobre:
# 1. Reinicializações do sistema (watchdog, memória, carga)
# 2. Status da interface web (mvision-web.service)
# =============================================================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Arquivo de relatório
REPORT_FILE="/tmp/diagnostico_mvision_$(date +%Y%m%d_%H%M%S).txt"

echo "============================================================================="
echo "                    DIAGNÓSTICO MVISION MONITOR"
echo "============================================================================="
echo "Data/Hora: $(date)"
echo "Relatório será salvo em: $REPORT_FILE"
echo "============================================================================="

# Função para imprimir seção
print_section() {
    echo ""
    echo -e "${BLUE}=== $1 ===${NC}"
    echo ""
    echo "=== $1 ===" >> "$REPORT_FILE"
}

# Função para executar comando e salvar
run_cmd() {
    local desc="$1"
    local cmd="$2"
    echo -e "${YELLOW}► $desc${NC}"
    echo "--- $desc ---" >> "$REPORT_FILE"
    eval "$cmd" 2>&1 | tee -a "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    echo ""
}

# Inicializa relatório
echo "RELATÓRIO DE DIAGNÓSTICO MVISION" > "$REPORT_FILE"
echo "Data: $(date)" >> "$REPORT_FILE"
echo "============================================" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# =============================================================================
# PROBLEMA 1: SISTEMA REINICIANDO
# =============================================================================
print_section "PROBLEMA 1: ANÁLISE DE REINICIALIZAÇÕES"

# 1.1 Histórico de reboots
run_cmd "Histórico de Reboots" "last reboot | head -20"

# 1.2 Uptime atual
run_cmd "Uptime do Sistema" "uptime"

# 1.3 Logs do Watchdog
print_section "WATCHDOG"
run_cmd "Logs do Watchdog Daemon" "cat /var/log/watchdog 2>/dev/null || echo 'Arquivo /var/log/watchdog não encontrado'"

# 1.4 Heartbeat
run_cmd "Status do Heartbeat" "ls -la /tmp/hospital-monitor-heartbeat 2>/dev/null && cat /tmp/hospital-monitor-heartbeat 2>/dev/null || echo 'Arquivo de heartbeat não encontrado'"

# 1.5 Logs do serviço principal
print_section "SERVIÇO HOSPITAL-MONITOR"
run_cmd "Status do Serviço" "systemctl status hospital-monitor 2>/dev/null || echo 'Serviço hospital-monitor não encontrado'"
run_cmd "Logs do Serviço (última hora)" "journalctl -u hospital-monitor --since '1 hour ago' --no-pager 2>/dev/null | tail -100 || echo 'Sem logs disponíveis'"

# 1.6 Uso de recursos
print_section "USO DE RECURSOS"
run_cmd "Processos Python" "ps aux | grep -E 'python|uvicorn' | grep -v grep || echo 'Nenhum processo Python encontrado'"
run_cmd "Memória Disponível" "free -h"
run_cmd "Carga do Sistema" "cat /proc/loadavg"
run_cmd "Top 10 Processos por Memória" "ps aux --sort=-%mem | head -11"
run_cmd "Top 10 Processos por CPU" "ps aux --sort=-%cpu | head -11"

# 1.7 Kernel messages (OOM, erros)
print_section "MENSAGENS DO KERNEL"
run_cmd "Últimas 50 mensagens do dmesg" "dmesg | tail -50"
run_cmd "Verificar OOM Killer" "dmesg | grep -i 'out of memory\|oom\|killed process' | tail -20 || echo 'Nenhum evento OOM encontrado'"

# =============================================================================
# PROBLEMA 2: INTERFACE WEB
# =============================================================================
print_section "PROBLEMA 2: INTERFACE WEB"

# 2.1 IP do Raspberry
run_cmd "Endereços IP" "hostname -I"

# 2.2 Status do serviço web
run_cmd "Status do mvision-web.service" "systemctl status mvision-web 2>/dev/null || echo 'Serviço mvision-web não encontrado'"

# 2.3 Logs do serviço web
run_cmd "Logs do mvision-web (últimas 50 linhas)" "journalctl -u mvision-web --no-pager -n 50 2>/dev/null || echo 'Sem logs disponíveis'"

# 2.4 Porta 8080
run_cmd "Verificar porta 8080" "ss -tlnp | grep 8080 || netstat -tlnp 2>/dev/null | grep 8080 || echo 'Porta 8080 não está em uso'"

# 2.5 Teste de acesso local
run_cmd "Teste de Acesso Local (curl)" "curl -s -o /dev/null -w 'HTTP Status: %{http_code}\n' http://localhost:8080 2>/dev/null || echo 'Falha ao conectar na porta 8080'"

# 2.6 Listar todos os serviços MVision
print_section "SERVIÇOS RELACIONADOS"
run_cmd "Serviços MVision/Hospital" "systemctl list-units --type=service | grep -E 'mvision|hospital|monitor' || echo 'Nenhum serviço encontrado'"

# =============================================================================
# RESUMO E RECOMENDAÇÕES
# =============================================================================
print_section "RESUMO DO DIAGNÓSTICO"

echo -e "${GREEN}Verificações Realizadas:${NC}"
echo "1. ✓ Histórico de reboots"
echo "2. ✓ Logs do watchdog"
echo "3. ✓ Status do heartbeat"
echo "4. ✓ Logs do hospital-monitor"
echo "5. ✓ Uso de memória e CPU"
echo "6. ✓ Mensagens do kernel (OOM)"
echo "7. ✓ Status da interface web"
echo "8. ✓ Conectividade na porta 8080"

echo ""
echo -e "${YELLOW}=== PRÓXIMOS PASSOS ===${NC}"
echo ""
echo "Analise o relatório completo em: $REPORT_FILE"
echo ""
echo "CHECKLIST DE AÇÕES:"
echo ""
echo "SE O SISTEMA ESTÁ REINICIANDO:"
echo "  □ Verificar se há eventos OOM no dmesg"
echo "  □ Verificar se o heartbeat está sendo atualizado"
echo "  □ Verificar carga do sistema (load > 24 causa reboot)"
echo "  □ Verificar memória livre (< 1 página causa reboot)"
echo ""
echo "SE A INTERFACE WEB NÃO FUNCIONA:"
echo "  □ Verificar se mvision-web.service está ativo"
echo "  □ Verificar se a porta 8080 está em uso"
echo "  □ Tentar: sudo systemctl restart mvision-web"
echo "  □ Acessar: http://$(hostname -I | awk '{print $1}'):8080"
echo ""

# =============================================================================
# COMANDOS ÚTEIS
# =============================================================================
print_section "COMANDOS ÚTEIS PARA CORREÇÃO"

echo "# Reiniciar serviço web:"
echo "sudo systemctl restart mvision-web"
echo ""
echo "# Reiniciar serviço de monitoramento:"
echo "sudo systemctl restart hospital-monitor"
echo ""
echo "# Ver logs em tempo real:"
echo "sudo journalctl -u hospital-monitor -f"
echo "sudo journalctl -u mvision-web -f"
echo ""
echo "# Verificar arquivos de configuração:"
echo "cat /etc/watchdog.conf"
echo "cat /etc/systemd/system/hospital-monitor.service"
echo "cat /etc/systemd/system/mvision-web.service"
echo ""

echo "============================================================================="
echo -e "${GREEN}Diagnóstico concluído!${NC}"
echo "Relatório salvo em: $REPORT_FILE"
echo "============================================================================="
