#!/bin/bash
# =============================================================================
# MVISION — Instalador consolidado e IDEMPOTENTE
# =============================================================================
#
# USO:
#   sudo bash deploy/install.sh                 # instala/repara tudo
#   sudo bash deploy/install.sh --prepare-image # prepara SD para virar imagem
#                                               # dourada (limpa segredos e
#                                               # habilita firstboot) e desliga
#
# Pode ser executado QUANTAS VEZES for necessário: cada etapa verifica o
# estado atual e só age no que falta. Substitui os antigos install-web.sh e
# setup-display.sh (mantidos como atalhos para este script).
#
# Funciona OFFLINE: dependências apt/pip só são instaladas se faltarem E
# houver internet; se faltarem sem internet, o instalador acusa com clareza.
#
# Ao final, roda a verificação (mvision-doctor). Só imprime "INSTALACAO OK"
# se o sistema estiver de fato operante.
# =============================================================================

set -u  # (sem -e: cada etapa trata o próprio erro para o resumo final)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_USER="${MVISION_USER:-tmed}"
SERVICE_GROUP="$SERVICE_USER"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ERRORS=0
WARNINGS=0

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[AVISO]${NC} $1"; WARNINGS=$((WARNINGS+1)); }
fail() { echo -e "  ${RED}[ERRO]${NC} $1"; ERRORS=$((ERRORS+1)); }

has_internet() {
    # Checagem local e rápida; nunca falha o script
    timeout 3 bash -c "exec 3<>/dev/tcp/deb.debian.org/80" 2>/dev/null && return 0
    return 1
}

PREPARE_IMAGE=0
[ "${1:-}" = "--prepare-image" ] && PREPARE_IMAGE=1

echo "=============================================================="
echo " MVISION - Instalador (idempotente)"
echo " Projeto: $PROJECT_DIR | Usuario do servico: $SERVICE_USER"
echo "=============================================================="

# -----------------------------------------------------------------------------
echo ""
echo "[1/10] Pre-requisitos"
# -----------------------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Execute como root: sudo bash deploy/install.sh${NC}"
    exit 1
fi
[ -f "$PROJECT_DIR/main.py" ] && ok "main.py encontrado" || { fail "main.py nao encontrado em $PROJECT_DIR"; exit 1; }

# Sistema operacional suportado: Raspberry Pi OS Bookworm (ou mais novo).
# Em versoes antigas o pip (--break-system-packages) e os caminhos de boot
# divergem e o instalador falharia com erros confusos la na frente.
OS_CODENAME=$(. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-desconhecido}")
case "$OS_CODENAME" in
    bookworm) ok "Sistema operacional: Bookworm (suportado)" ;;
    trixie)   warn "Sistema operacional: Trixie - mais novo que o validado (Bookworm); prossiga com atencao" ;;
    *)
        if [ "${MVISION_SKIP_OS_CHECK:-0}" = "1" ]; then
            warn "SO '$OS_CODENAME' nao suportado - prosseguindo por MVISION_SKIP_OS_CHECK=1"
        else
            echo -e "${RED}Este instalador requer Raspberry Pi OS BOOKWORM (detectado: $OS_CODENAME).${NC}"
            echo "Grave o SD com Raspberry Pi OS Bookworm 64-bit e rode novamente."
            echo "(Para forcar em outro sistema: MVISION_SKIP_OS_CHECK=1 sudo -E bash deploy/install.sh)"
            exit 1
        fi
        ;;
esac
PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
ok "Python detectado: ${PY_VER:-ausente} (Bookworm usa 3.11)"

# Com o overlay de protecao do SD ativo, TUDO que este instalador escreve
# (units, /etc, pacotes) iria para a RAM e sumiria no proximo reboot.
if [ "$(findmnt -no FSTYPE / 2>/dev/null)" = "overlay" ]; then
    echo -e "${RED}Protecao do SD (overlay) esta ATIVA - a instalacao nao persistiria.${NC}"
    echo "Desative antes: sudo mvision-overlay --disable && sudo reboot"
    exit 1
fi

# Auto-protecao: codigo copiado do Windows (FileZilla/SFTP) pode vir com CRLF,
# que quebra scripts e units no Linux. Normaliza tudo antes de usar.
CRLF_COUNT=$(grep -rlI $'\r' "$SCRIPT_DIR" 2>/dev/null | wc -l)
if [ "$CRLF_COUNT" -gt 0 ]; then
    find "$SCRIPT_DIR" -type f \( -name '*.sh' -o -name '*.service' -o -name '*.timer' \) \
        -exec sed -i 's/\r$//' {} +
    ok "Fins de linha normalizados em $CRLF_COUNT arquivo(s) de deploy (CRLF -> LF)"
else
    ok "Fins de linha dos scripts OK"
fi
id "$SERVICE_USER" &>/dev/null && ok "Usuario $SERVICE_USER existe" || {
    useradd -m -s /bin/bash "$SERVICE_USER" && ok "Usuario $SERVICE_USER criado" || fail "Falha ao criar usuario $SERVICE_USER"
}

# -----------------------------------------------------------------------------
echo ""
echo "[2/10] Dependencias do sistema (apt)"
# -----------------------------------------------------------------------------
# git NAO entra na lista: o dispositivo nunca usa git (politica de seguranca)
APT_PKGS=(python3-pip python3-opencv python3-picamera2 curl parted)
MISSING_APT=()
for pkg in "${APT_PKGS[@]}"; do
    dpkg -s "$pkg" &>/dev/null || MISSING_APT+=("$pkg")
done
if [ ${#MISSING_APT[@]} -eq 0 ]; then
    ok "Todos os pacotes apt presentes"
elif has_internet; then
    echo "  Instalando: ${MISSING_APT[*]}"
    apt-get update -qq && apt-get install -y -qq "${MISSING_APT[@]}" \
        && ok "Pacotes instalados" || fail "Falha no apt-get install"
else
    fail "Pacotes faltando SEM internet: ${MISSING_APT[*]} (use a imagem dourada ou conecte a rede)"
fi

# -----------------------------------------------------------------------------
echo ""
echo "[3/10] Dependencias Python"
# -----------------------------------------------------------------------------
PY_CHECK=$(sudo -u "$SERVICE_USER" python3 - <<'EOF' 2>/dev/null
mods = ["cv2", "numpy", "ultralytics", "fastapi", "uvicorn", "pydantic"]
missing = []
for m in mods:
    try:
        __import__(m)
    except Exception:
        missing.append(m)
print(",".join(missing))
EOF
)
if [ -z "$PY_CHECK" ]; then
    ok "Modulos Python presentes (cv2, ultralytics, fastapi, uvicorn)"
elif has_internet; then
    echo "  Instalando modulos Python faltantes: $PY_CHECK"
    if [ -f "$PROJECT_DIR/requirements_raspberry.txt" ]; then
        pip3 install --quiet --break-system-packages -r "$PROJECT_DIR/requirements_raspberry.txt" \
            && ok "Dependencias Python instaladas" || fail "Falha no pip install"
    else
        pip3 install --quiet --break-system-packages ultralytics fastapi uvicorn python-multipart pydantic \
            && ok "Dependencias Python instaladas" || fail "Falha no pip install"
    fi
else
    fail "Modulos Python faltando SEM internet: $PY_CHECK (use a imagem dourada)"
fi

# -----------------------------------------------------------------------------
echo ""
echo "[4/10] Modelos YOLO"
# -----------------------------------------------------------------------------
for model in "$PROJECT_DIR/yolov8n-pose.pt" "$PROJECT_DIR/yolov8l.pt"; do
    name=$(basename "$model")
    if [ ! -f "$model" ]; then
        fail "$name nao encontrado (copie o arquivo real via FileZilla/SFTP ou pendrive)"
    elif head -c 24 "$model" | grep -q "version https"; then
        fail "$name e um PONTEIRO Git LFS, nao o modelo real - copie o .pt verdadeiro via FileZilla/SFTP ou pendrive (o dispositivo nao usa git)"
    else
        ok "$name valido ($(du -h "$model" | cut -f1))"
    fi
done
# ASETO e opcional (validacao cruzada da calibracao)
if [ -f "$PROJECT_DIR/aseto_v3_best.pt" ] && ! head -c 24 "$PROJECT_DIR/aseto_v3_best.pt" | grep -q "version https"; then
    ok "aseto_v3_best.pt valido (validacao cruzada ativa)"
else
    warn "aseto_v3_best.pt ausente/invalido - validacao cruzada da calibracao ficara inativa"
fi

# -----------------------------------------------------------------------------
echo ""
echo "[5/10] Servicos systemd (fonte unica: deploy/*.service)"
# -----------------------------------------------------------------------------
install_unit() {
    local template="$1" target="$2"
    # Adapta caminhos/usuario do template para esta instalacao
    sed -e "s|/mvision|$PROJECT_DIR|g" \
        -e "s|User=tmed|User=$SERVICE_USER|" \
        -e "s|Group=tmed|Group=$SERVICE_GROUP|" \
        -e "s|/home/tmed|/home/$SERVICE_USER|g" \
        "$template" > "/tmp/$(basename "$target")"
    if [ -f "$target" ] && cmp -s "/tmp/$(basename "$target")" "$target"; then
        ok "$(basename "$target") ja atualizado"
    else
        cp "/tmp/$(basename "$target")" "$target"
        NEED_DAEMON_RELOAD=1
        ok "$(basename "$target") instalado/atualizado"
    fi
    rm -f "/tmp/$(basename "$target")"
}
NEED_DAEMON_RELOAD=0
install_unit "$SCRIPT_DIR/hospital-monitor.service" /etc/systemd/system/hospital-monitor.service
install_unit "$SCRIPT_DIR/mvision-web.service" /etc/systemd/system/mvision-web.service
install_unit "$SCRIPT_DIR/mvision-web-healthcheck.service" /etc/systemd/system/mvision-web-healthcheck.service
install_unit "$SCRIPT_DIR/mvision-web-healthcheck.timer" /etc/systemd/system/mvision-web-healthcheck.timer
install_unit "$SCRIPT_DIR/mvision-usb-update.service" /etc/systemd/system/mvision-usb-update.service
[ "$NEED_DAEMON_RELOAD" = 1 ] && systemctl daemon-reload

# -----------------------------------------------------------------------------
echo ""
echo "[6/10] Configuracao do sistema (journald, watchdog, sudoers)"
# -----------------------------------------------------------------------------
mkdir -p /etc/systemd/journald.conf.d
if [ ! -f /etc/systemd/journald.conf.d/mvision.conf ]; then
    cat > /etc/systemd/journald.conf.d/mvision.conf << 'EOF'
[Journal]
SystemMaxUse=200M
SystemKeepFree=1G
EOF
    systemctl restart systemd-journald || true
    ok "journald limitado a 200M"
else
    ok "journald ja configurado"
fi

mkdir -p /etc/systemd/system.conf.d
if [ ! -f /etc/systemd/system.conf.d/mvision-watchdog.conf ]; then
    cat > /etc/systemd/system.conf.d/mvision-watchdog.conf << 'EOF'
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
EOF
    # daemon-reexec aplica o RuntimeWatchdogSec JA neste boot (sem ele, o
    # watchdog so armaria no proximo reboot e o doctor acusaria falha)
    systemctl daemon-reexec 2>/dev/null || true
    ok "Watchdog de hardware configurado e armado"
else
    ok "Watchdog de hardware ja configurado"
fi

SUDOERS_FILE=/etc/sudoers.d/mvision-web
SUDOERS_LINE="$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart hospital-monitor"
if [ ! -f "$SUDOERS_FILE" ] || ! grep -qF "$SUDOERS_LINE" "$SUDOERS_FILE"; then
    echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    ok "Regra sudoers do botao de restart criada"
else
    ok "Regra sudoers ja presente"
fi

# -----------------------------------------------------------------------------
echo ""
echo "[7/10] Display/boot (HDMI sem monitor)"
# -----------------------------------------------------------------------------
BOOT_CONFIG="/boot/config.txt"
[ -f "/boot/firmware/config.txt" ] && BOOT_CONFIG="/boot/firmware/config.txt"
if [ -f "$BOOT_CONFIG" ]; then
    # Backup UNICO (nao acumula a cada execucao)
    [ -f "${BOOT_CONFIG}.mvision-backup" ] || cp "$BOOT_CONFIG" "${BOOT_CONFIG}.mvision-backup"
    if ! grep -q "hdmi_force_hotplug=1" "$BOOT_CONFIG"; then
        { echo ""; echo "# MVision: HDMI ativo mesmo sem monitor"; echo "hdmi_force_hotplug=1"; \
          echo "hdmi_group=1"; echo "hdmi_mode=4"; } >> "$BOOT_CONFIG"
        ok "HDMI hotplug configurado (efetivo apos reboot)"
    else
        ok "HDMI hotplug ja configurado"
    fi
    # Watchdog de hardware: habilita explicitamente o chip (bcm2835_wdt).
    # Sem isto o RuntimeWatchdogSec do systemd pode nao ter dispositivo
    # para alimentar e a protecao contra travamento de kernel fica inerte.
    if ! grep -q "^dtparam=watchdog=on" "$BOOT_CONFIG"; then
        { echo ""; echo "# MVision: watchdog de hardware"; echo "dtparam=watchdog=on"; } >> "$BOOT_CONFIG"
        ok "Watchdog de hardware habilitado no boot (efetivo apos reboot)"
    else
        ok "Watchdog de hardware ja habilitado no boot"
    fi
else
    warn "config.txt nao encontrado (nao e Raspberry Pi?) - etapa de display pulada"
fi

# -----------------------------------------------------------------------------
echo ""
echo "[8/10] Permissoes e grupos"
# -----------------------------------------------------------------------------
for grp in gpio video i2c; do
    if getent group "$grp" >/dev/null && ! id -nG "$SERVICE_USER" | grep -qw "$grp"; then
        usermod -aG "$grp" "$SERVICE_USER" && ok "Usuario adicionado ao grupo $grp"
    fi
done
ok "Grupos verificados"
# Apenas diretorios de escrita do runtime (nao o projeto inteiro a cada execucao)
mkdir -p "$PROJECT_DIR/data/logs" "$PROJECT_DIR/data/alert_images" "$PROJECT_DIR/config"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$PROJECT_DIR/data" "$PROJECT_DIR/config"
ok "Diretorios de runtime prontos (data/, config/)"

# -----------------------------------------------------------------------------
echo ""
echo "[9/10] Ferramentas (mvision-doctor, atualizador USB, firstboot)"
# -----------------------------------------------------------------------------
install -m 755 "$SCRIPT_DIR/mvision-doctor.sh" /usr/local/bin/mvision-doctor
ok "mvision-doctor instalado (rode 'mvision-doctor' para diagnostico)"
install -m 755 "$SCRIPT_DIR/usb-update.sh" /usr/local/bin/mvision-usb-update
ok "Atualizador USB instalado"
install -m 755 "$SCRIPT_DIR/firstboot.sh" /usr/local/bin/mvision-firstboot
install -m 755 "$SCRIPT_DIR/setup-overlay.sh" /usr/local/bin/mvision-overlay
ok "mvision-overlay instalado (protecao do SD: mvision-overlay --status)"
install_unit "$SCRIPT_DIR/mvision-firstboot.service" /etc/systemd/system/mvision-firstboot.service
[ "$NEED_DAEMON_RELOAD" = 1 ] && systemctl daemon-reload

# Version-stamp: o dispositivo nao tem git (politica), entao a versao
# instalada e identificada por data + hash do conteudo do codigo.
CODE_HASH=$( (cat "$PROJECT_DIR/main.py" "$PROJECT_DIR/config.py" "$PROJECT_DIR"/modules/*.py \
    "$PROJECT_DIR"/web/backend/*.py "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/*.service 2>/dev/null) \
    | sha256sum | cut -c1-12)
RELEASE_TAG=$(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo "sem-tag")
cat > /etc/mvision-version << EOF
release=$RELEASE_TAG
code_hash=$CODE_HASH
installed_at=$(date '+%Y-%m-%d %H:%M:%S')
EOF
ok "Versao registrada: $RELEASE_TAG ($CODE_HASH)"

# -----------------------------------------------------------------------------
echo ""
echo "[10/10] Habilitando e iniciando servicos"
# -----------------------------------------------------------------------------
systemctl enable hospital-monitor mvision-web mvision-web-healthcheck.timer mvision-usb-update &>/dev/null
ok "Servicos habilitados no boot"

if [ "$PREPARE_IMAGE" = 1 ]; then
    echo ""
    echo "=============================================================="
    echo " PREPARANDO SD PARA IMAGEM DOURADA"
    echo "=============================================================="
    if [ "$(findmnt -no FSTYPE / 2>/dev/null)" = "overlay" ]; then
        fail "Overlay ativo - a imagem dourada deve ser selada com overlay DESATIVADO (mvision-overlay --disable + reboot)"
        exit 1
    fi
    # Politica de protecao do SD nas unidades clonadas: o firstboot le este
    # arquivo. ENABLE_OVERLAY=1 -> reserva particao de dados, migra e liga o
    # overlay automaticamente. Deixe 0 ate o teste de queda de energia (V9)
    # ser revalidado com o overlay ativo.
    BOOT_DIR="/boot/firmware"; [ -d "$BOOT_DIR" ] || BOOT_DIR="/boot"
    if [ ! -f "$BOOT_DIR/mvision-firstboot.conf" ]; then
        cat > "$BOOT_DIR/mvision-firstboot.conf" << 'EOF'
# Configuracao do primeiro boot das unidades clonadas desta imagem
# ENABLE_OVERLAY=1 liga a protecao do SD (raiz somente-leitura) no firstboot
ENABLE_OVERLAY=0
# Tamanho da particao de dados persistente (GB) reservada no firstboot
DATA_SIZE_GB=4
EOF
        ok "mvision-firstboot.conf criado em $BOOT_DIR (ENABLE_OVERLAY=0)"
    else
        ok "mvision-firstboot.conf ja presente em $BOOT_DIR"
    fi
    systemctl stop hospital-monitor mvision-web &>/dev/null
    # Remove segredos/identidade que NAO podem ser clonados entre unidades
    rm -f "$PROJECT_DIR/config/web_auth.json" \
          "$PROJECT_DIR/config/environment.json" \
          "$PROJECT_DIR/config/runtime_config.json" \
          "$PROJECT_DIR/data/bed_reference.json"
    rm -rf "$PROJECT_DIR/data/alert_images" "$PROJECT_DIR/data/logs"
    journalctl --rotate &>/dev/null; journalctl --vacuum-time=1s &>/dev/null
    systemctl enable mvision-firstboot &>/dev/null
    ok "Segredos limpos e mvision-firstboot habilitado"
    echo ""
    echo "Desligue com 'sudo poweroff', remova o SD e extraia a imagem"
    echo "(ver doc/IMAGEM_DOURADA.md). NAO ligue este SD antes de clonar."
    exit 0
fi

systemctl restart mvision-web
# O timer foi apenas habilitado acima; sem start ele so roda no proximo boot
# e o painel ficaria sem supervisao ate la
systemctl start mvision-web-healthcheck.timer 2>/dev/null || true
systemctl restart hospital-monitor
ok "Servicos (re)iniciados"

# -----------------------------------------------------------------------------
echo ""
echo "=============================================================="
echo " VERIFICACAO FINAL (mvision-doctor)"
echo "=============================================================="
sleep 8  # tempo para os servicos subirem
/usr/local/bin/mvision-doctor --install-check
DOCTOR_RC=$?

echo ""
echo "=============================================================="
if [ "$ERRORS" -eq 0 ] && [ "$DOCTOR_RC" -eq 0 ]; then
    echo -e " ${GREEN}INSTALACAO OK${NC} (avisos: $WARNINGS)"
    IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo ""
    echo " Painel web:  http://${IP_ADDR:-<ip-do-dispositivo>}:8080"
    echo " Senha padrao: mvision123 (o painel exigira a troca)"
    echo " Diagnostico:  mvision-doctor"
    exit 0
else
    echo -e " ${RED}INSTALACAO COM PROBLEMAS${NC} (erros: $ERRORS, verificacao: $DOCTOR_RC)"
    echo " Revise as linhas [ERRO] acima e rode novamente: sudo bash deploy/install.sh"
    exit 1
fi
