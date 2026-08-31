#!/bin/bash
# =============================================================================
# mvision-overlay — Protecao do SD card (overlayfs + particao de dados)
# =============================================================================
#
# A raiz do sistema vira SOMENTE-LEITURA (overlay em RAM): quedas de energia
# nao corrompem mais o SD. O que precisa persistir (config/, data/) mora numa
# particao gravavel dedicada (label MVISIONDATA), montada em /mvision-data e
# ligada ao projeto por symlinks.
#
# USO:
#   sudo mvision-overlay --status        # mostra o estado atual
#   sudo mvision-overlay --prepare-data  # cria a particao de dados (1x)
#   sudo mvision-overlay --migrate       # move data/ e config/ para a particao
#   sudo mvision-overlay --enable        # liga o overlay (exige reboot)
#   sudo mvision-overlay --disable       # desliga o overlay (exige reboot)
#
# Ordem tipica: --prepare-data -> --migrate -> --enable -> reboot.
# Para atualizar codigo/sistema: --disable -> reboot -> mudanca -> --enable.
# O atualizador USB (mvision-usb-update) faz esse ciclo sozinho.
#
# ATENCAO: --prepare-data precisa de espaco LIVRE apos a particao raiz.
# No fluxo da imagem dourada o firstboot ja reserva esse espaco; num SD onde
# a raiz ocupa o disco inteiro, use a imagem dourada ou reparticione offline.
# =============================================================================

set -u

DATA_LABEL="MVISIONDATA"
DATA_MOUNT="/mvision-data"
DATA_SIZE_GB="${MVISION_DATA_GB:-4}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[AVISO]${NC} $1"; }
die()  { echo -e "  ${RED}[ERRO]${NC} $1"; exit 1; }

[ "$EUID" -eq 0 ] || die "Execute como root: sudo mvision-overlay <acao>"

project_dir() {
    local unit_dir
    unit_dir=$(grep -oP '^WorkingDirectory=\K.*' /etc/systemd/system/hospital-monitor.service 2>/dev/null)
    echo "${MVISION_DIR:-${unit_dir:-/mvision}}"
}

overlay_active() { [ "$(findmnt -no FSTYPE / 2>/dev/null)" = "overlay" ]; }

data_partition() { blkid -L "$DATA_LABEL" 2>/dev/null; }

data_mounted() { findmnt -no TARGET "$DATA_MOUNT" &>/dev/null; }

cmd_status() {
    echo "=== mvision-overlay: estado ==="
    if overlay_active; then
        echo -e "  Overlay (raiz somente-leitura): ${GREEN}ATIVO${NC} - SD protegido"
    else
        echo -e "  Overlay (raiz somente-leitura): ${YELLOW}INATIVO${NC} - SD sujeito a corrupcao"
    fi
    local part
    part=$(data_partition)
    if [ -n "$part" ]; then
        echo "  Particao de dados: $part (label $DATA_LABEL)"
        if data_mounted; then
            echo -e "  Montagem em $DATA_MOUNT: ${GREEN}OK${NC} ($(df -h "$DATA_MOUNT" | awk 'NR==2 {print $4}') livres)"
        else
            echo -e "  Montagem em $DATA_MOUNT: ${RED}AUSENTE${NC}"
        fi
    else
        echo -e "  Particao de dados: ${YELLOW}NAO EXISTE${NC} (rode --prepare-data)"
    fi
    local pd
    pd=$(project_dir)
    for d in data config; do
        if [ -L "$pd/$d" ]; then
            echo "  $pd/$d -> $(readlink "$pd/$d")"
        else
            echo -e "  $pd/$d: ${YELLOW}diretorio local (nao migrado)${NC}"
        fi
    done
}

cmd_prepare_data() {
    if [ -n "$(data_partition)" ]; then
        ok "Particao $DATA_LABEL ja existe: $(data_partition)"
        ensure_fstab_and_mount
        return 0
    fi
    overlay_active && die "Overlay ativo - desative primeiro (--disable + reboot)"

    local root_part root_dev part_prefix disk_sectors last_end free_sectors start_sector
    root_part=$(findmnt -no SOURCE /)
    root_dev="/dev/$(lsblk -no pkname "$root_part")"
    disk_sectors=$(blockdev --getsz "$root_dev")
    # Fim (em setores de 512B) da ultima particao existente
    last_end=$(parted -sm "$root_dev" unit s print 2>/dev/null | awk -F: '/^[0-9]/ {gsub("s","",$3); if ($3+0 > max) max=$3+0} END {print max}')
    [ -n "$last_end" ] && [ "$last_end" -gt 0 ] || die "Nao consegui ler a tabela de particoes de $root_dev"
    free_sectors=$((disk_sectors - last_end - 1))
    local need_sectors=$((DATA_SIZE_GB * 2097152 / 2))  # aceita a partir de metade do alvo
    if [ "$free_sectors" -lt "$need_sectors" ]; then
        die "Espaco livre insuficiente apos a raiz ($((free_sectors/2048)) MB). \
Use a imagem dourada (firstboot reserva o espaco) ou reparticione offline."
    fi
    start_sector=$(( (last_end + 2048) / 2048 * 2048 ))  # alinha em 1MB
    echo "  Criando particao de dados em $root_dev (${free_sectors} setores livres)..."
    parted -s "$root_dev" mkpart primary ext4 "${start_sector}s" 100% || die "parted falhou"
    partprobe "$root_dev" 2>/dev/null; sleep 2
    local new_part
    new_part=$(lsblk -nrpo NAME,TYPE "$root_dev" | awk '$2=="part" {p=$1} END {print p}')
    [ -b "$new_part" ] || die "Particao criada mas nao encontrada"
    mkfs.ext4 -q -F -L "$DATA_LABEL" "$new_part" || die "mkfs.ext4 falhou"
    ok "Particao $new_part criada e formatada (label $DATA_LABEL)"
    ensure_fstab_and_mount
}

ensure_fstab_and_mount() {
    mkdir -p "$DATA_MOUNT"
    if ! grep -q "LABEL=$DATA_LABEL" /etc/fstab; then
        echo "LABEL=$DATA_LABEL  $DATA_MOUNT  ext4  defaults,noatime,nofail  0  2" >> /etc/fstab
        ok "Entrada no fstab criada"
    fi
    if ! data_mounted; then
        systemctl daemon-reload 2>/dev/null
        mount "$DATA_MOUNT" || die "Falha ao montar $DATA_MOUNT"
    fi
    ok "$DATA_MOUNT montado"
}

cmd_migrate() {
    data_mounted || die "Particao de dados nao montada - rode --prepare-data antes"
    overlay_active && die "Overlay ativo - desative primeiro (--disable + reboot)"
    local pd svc_user
    pd=$(project_dir)
    svc_user=$(stat -c %U "$pd" 2>/dev/null || echo tmed)

    local was_running=0
    systemctl is-active --quiet hospital-monitor && was_running=1
    systemctl stop hospital-monitor mvision-web 2>/dev/null

    for d in data config; do
        if [ -L "$pd/$d" ]; then
            ok "$pd/$d ja e symlink"
            continue
        fi
        mkdir -p "$DATA_MOUNT/$d"
        if [ -d "$pd/$d" ]; then
            # cp+rm (nao mv): origem e destino em filesystems diferentes
            cp -a "$pd/$d/." "$DATA_MOUNT/$d/" || die "Falha ao copiar $d para $DATA_MOUNT"
            rm -rf "$pd/$d"
        fi
        ln -s "$DATA_MOUNT/$d" "$pd/$d"
        ok "$pd/$d migrado para $DATA_MOUNT/$d"
    done
    chown -R "$svc_user:$svc_user" "$DATA_MOUNT"

    if [ "$was_running" = 1 ]; then
        systemctl start mvision-web hospital-monitor 2>/dev/null
        ok "Servicos reiniciados"
    fi
}

cmd_enable() {
    overlay_active && { ok "Overlay ja ativo"; return 0; }
    data_mounted || die "Particao de dados nao montada - rode --prepare-data e --migrate antes"
    local pd
    pd=$(project_dir)
    for d in data config; do
        [ -L "$pd/$d" ] || die "$pd/$d nao migrado - rode --migrate antes (senao os dados irao para a RAM e serao PERDIDOS)"
    done
    command -v raspi-config >/dev/null || die "raspi-config nao encontrado (nao e Raspberry Pi OS?)"
    raspi-config nonint enable_overlayfs || die "raspi-config enable_overlayfs falhou"
    ok "Overlay habilitado - REINICIE para ativar: sudo reboot"
}

cmd_disable() {
    if ! overlay_active && ! raspi-config nonint get_overlay_conf 2>/dev/null; then
        ok "Overlay ja inativo"
        return 0
    fi
    command -v raspi-config >/dev/null || die "raspi-config nao encontrado"
    raspi-config nonint disable_overlayfs || die "raspi-config disable_overlayfs falhou"
    ok "Overlay desabilitado - REINICIE para aplicar: sudo reboot"
}

case "${1:-}" in
    --status)       cmd_status ;;
    --prepare-data) cmd_prepare_data ;;
    --migrate)      cmd_migrate ;;
    --enable)       cmd_enable ;;
    --disable)      cmd_disable ;;
    *) echo "Uso: mvision-overlay --status | --prepare-data | --migrate | --enable | --disable"; exit 1 ;;
esac
