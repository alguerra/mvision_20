#!/bin/bash
# =============================================================================
# mvision-doctor — Autodiagnóstico do MVISION
# =============================================================================
#
# USO:
#   mvision-doctor                  # diagnostico completo
#   mvision-doctor --install-check  # usado pelo instalador (mesmos checks)
#
# Imprime PASS/FALHA/AVISO por item, em português, para que um técnico sem
# conhecimento de Linux consiga reportar exatamente o que está errado.
# Sai com codigo 0 se nenhum item critico falhou.
# =============================================================================

PROJECT_DIR="${MVISION_DIR:-/mvision}"
# Fallback: descobre pelo unit instalado
if [ ! -f "$PROJECT_DIR/main.py" ] && [ -f /etc/systemd/system/hospital-monitor.service ]; then
    UNIT_DIR=$(grep -oP '^WorkingDirectory=\K.*' /etc/systemd/system/hospital-monitor.service 2>/dev/null)
    [ -n "$UNIT_DIR" ] && PROJECT_DIR="$UNIT_DIR"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
FAILS=0
WARNS=0

pass() { echo -e "  ${GREEN}[PASS]${NC}  $1"; }
failc() { echo -e "  ${RED}[FALHA]${NC} $1"; FAILS=$((FAILS+1)); }
warnc() { echo -e "  ${YELLOW}[AVISO]${NC} $1"; WARNS=$((WARNS+1)); }

echo "=============================================================="
echo " MVISION DOCTOR - $(date '+%Y-%m-%d %H:%M:%S')"
echo " Projeto: $PROJECT_DIR"
echo "=============================================================="

echo ""
echo "--- Servicos ---"
for svc in hospital-monitor mvision-web; do
    if systemctl is-active --quiet "$svc"; then
        restarts=$(systemctl show "$svc" -p NRestarts --value 2>/dev/null)
        if [ "${restarts:-0}" -gt 3 ]; then
            warnc "$svc ativo, mas com $restarts reinicios (verifique: journalctl -u $svc -n 50)"
        else
            pass "$svc ativo"
        fi
    else
        failc "$svc NAO esta rodando (journalctl -u $svc -n 50 mostra o motivo)"
    fi
done
systemctl is-enabled --quiet mvision-web-healthcheck.timer 2>/dev/null \
    && pass "Healthcheck do painel habilitado" \
    || warnc "Healthcheck do painel nao habilitado (rode o instalador)"

echo ""
echo "--- Monitor de leito (sinal de vida) ---"
STATUS_FILE=/tmp/mvision_status.json
if [ -f "$STATUS_FILE" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$STATUS_FILE") ))
    STATE=$(grep -oP '"state":\s*"\K[^"]*' "$STATUS_FILE" 2>/dev/null)
    if [ "$AGE" -le 90 ]; then
        pass "Monitor publicando status ha ${AGE}s (estado: ${STATE:-?})"
    else
        failc "Monitor SEM SINAL ha ${AGE}s (servico pode estar travado/reiniciando)"
    fi
else
    failc "Monitor nunca publicou status (arquivo $STATUS_FILE ausente)"
fi

echo ""
echo "--- Camera ---"
if command -v libcamera-hello &>/dev/null && timeout 10 libcamera-hello --list-cameras 2>/dev/null | grep -q ":"; then
    pass "Camera CSI detectada (libcamera)"
elif ls /dev/video* &>/dev/null; then
    pass "Dispositivo de video presente ($(ls /dev/video* | head -1))"
else
    failc "NENHUMA camera detectada (verifique o cabo flat/USB)"
fi

echo ""
echo "--- Modelos ---"
for model in yolov8n-pose.pt yolov8l.pt; do
    f="$PROJECT_DIR/$model"
    if [ ! -f "$f" ]; then
        failc "$model ausente"
    elif head -c 24 "$f" | grep -q "version https"; then
        failc "$model e ponteiro Git LFS (rode: git lfs pull com internet)"
    else
        pass "$model valido ($(du -h "$f" | cut -f1))"
    fi
done
[ -f "$PROJECT_DIR/aseto_v3_best.pt" ] && ! head -c 24 "$PROJECT_DIR/aseto_v3_best.pt" | grep -q "version https" \
    && pass "aseto_v3_best.pt valido (validacao de calibracao ativa)" \
    || warnc "ASETO ausente - validacao cruzada da calibracao inativa"

echo ""
echo "--- Calibracao da cama ---"
BED_REF="$PROJECT_DIR/data/bed_reference.json"
if [ -f "$BED_REF" ] && python3 -c "import json;d=json.load(open('$BED_REF'));assert len(d['bbox'])==4" 2>/dev/null; then
    pass "Referencia da cama valida: $(python3 -c "import json;print(json.load(open('$BED_REF'))['bbox'])" 2>/dev/null)"
else
    warnc "Sem referencia de cama valida (sera calibrada na proxima inicializacao com cama vazia)"
fi

echo ""
echo "--- Recursos ---"
DISK_FREE_MB=$(df -m "$PROJECT_DIR" | awk 'NR==2 {print $4}')
if [ "${DISK_FREE_MB:-0}" -ge 1024 ]; then
    pass "Espaco em disco: ${DISK_FREE_MB} MB livres"
else
    failc "Espaco em disco BAIXO: ${DISK_FREE_MB} MB livres (minimo 1024)"
fi

MEM_AVAIL_MB=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
if [ "${MEM_AVAIL_MB:-0}" -ge 300 ]; then
    pass "Memoria disponivel: ${MEM_AVAIL_MB} MB"
else
    warnc "Memoria disponivel baixa: ${MEM_AVAIL_MB} MB"
fi

MON_PID=$(systemctl show hospital-monitor -p MainPID --value 2>/dev/null)
if [ -n "$MON_PID" ] && [ "$MON_PID" != "0" ] && [ -f "/proc/$MON_PID/status" ]; then
    RSS_MB=$(awk '/VmRSS/ {print int($2/1024)}' "/proc/$MON_PID/status")
    if [ "${RSS_MB:-0}" -le 700 ]; then
        pass "Memoria do monitor: ${RSS_MB} MB (limite 768)"
    else
        warnc "Memoria do monitor alta: ${RSS_MB} MB (limite 768 - risco de restart)"
    fi
fi

if command -v vcgencmd &>/dev/null; then
    THROTTLED=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
    if [ "$THROTTLED" = "0x0" ]; then
        pass "Sem throttling termico/eletrico"
    else
        warnc "Throttling detectado ($THROTTLED) - verifique fonte e dissipador (FPS degradado!)"
    fi
    TEMP=$(vcgencmd measure_temp 2>/dev/null | grep -oP "[0-9.]+")
    [ -n "$TEMP" ] && echo "         Temperatura do SoC: ${TEMP}C"
fi

echo ""
echo "--- Sistema ---"
YEAR=$(date +%Y)
if [ "$YEAR" -ge 2026 ]; then
    pass "Relogio plausivel: $(date '+%Y-%m-%d %H:%M')"
else
    warnc "Relogio IMplausivel ($(date '+%Y-%m-%d')) - logs terao data errada (instalar RTC)"
fi

grep -q "RuntimeWatchdogSec" /etc/systemd/system.conf.d/mvision-watchdog.conf 2>/dev/null \
    && pass "Watchdog de hardware configurado" \
    || warnc "Watchdog de hardware nao configurado (rode o instalador + reboot)"

grep -q "SystemMaxUse" /etc/systemd/journald.conf.d/mvision.conf 2>/dev/null \
    && pass "Limite do journald configurado" \
    || warnc "journald sem limite (rode o instalador)"

[ -f /etc/sudoers.d/mvision-web ] \
    && pass "Regra de restart do painel presente" \
    || warnc "Sudoers do painel ausente (botao de restart falhara)"

if curl -fs -m 5 "http://localhost:8080/" -o /dev/null 2>/dev/null; then
    pass "Painel web respondendo na porta 8080"
else
    failc "Painel web NAO responde na porta 8080"
fi

VERSION=$(cd "$PROJECT_DIR" 2>/dev/null && git log -1 --format="%h %ad" --date=short 2>/dev/null)
[ -n "$VERSION" ] && echo "         Versao instalada: $VERSION"

echo ""
echo "=============================================================="
if [ "$FAILS" -eq 0 ]; then
    echo -e " ${GREEN}RESULTADO: SISTEMA OPERANTE${NC} (falhas: 0, avisos: $WARNS)"
    exit 0
else
    echo -e " ${RED}RESULTADO: $FAILS FALHA(S)${NC} (avisos: $WARNS)"
    echo " Informe as linhas [FALHA] acima ao suporte."
    exit 1
fi
