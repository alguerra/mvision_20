#!/bin/bash
# Script de instalacao do Sistema de Monitoramento no Raspberry Pi
# Executar como root: sudo bash install.sh

set -e

echo "=============================================="
echo "Instalacao do Sistema de Monitoramento"
echo "=============================================="

# Diretorios
INSTALL_DIR="/opt/hospital-monitor"
CONFIG_DIR="/opt/hospital-monitor/config"
LOG_DIR="/var/log/hospital-monitor"
DATA_DIR="/opt/hospital-monitor/data"
SOURCE_DIR="$(dirname "$0")/.."

# 1. Cria diretorios
echo "[1/7] Criando diretorios..."
mkdir -p $INSTALL_DIR
mkdir -p $CONFIG_DIR
mkdir -p $LOG_DIR
mkdir -p $DATA_DIR/logs
mkdir -p $DATA_DIR/alert_images

# 2. Copia arquivos do projeto
echo "[2/7] Copiando arquivos do projeto..."
cp -r $SOURCE_DIR/main.py $INSTALL_DIR/
cp -r $SOURCE_DIR/config.py $INSTALL_DIR/
cp -r $SOURCE_DIR/modules $INSTALL_DIR/
cp -r $SOURCE_DIR/gui $INSTALL_DIR/
cp -r $SOURCE_DIR/requirements_raspberry.txt $INSTALL_DIR/ 2>/dev/null || true

# 3. Copia pasta data (referência de cama, logs, etc)
echo "[3/7] Copiando dados pre-configurados..."
if [ -d "$SOURCE_DIR/data" ]; then
    # Copia mantendo arquivos existentes (nao sobrescreve)
    cp -rn $SOURCE_DIR/data/* $DATA_DIR/ 2>/dev/null || true
    echo "  Dados copiados de $SOURCE_DIR/data"

    # Verifica se tem referencia de cama
    if [ -f "$DATA_DIR/bed_reference.json" ]; then
        echo "  Referencia de cama encontrada: bed_reference.json"
    fi
else
    echo "  Pasta data/ nao encontrada no source, criando estrutura vazia"
fi

# 4. Copia configuracao de ambiente
echo "[4/7] Configurando ambiente..."
if [ ! -f "$CONFIG_DIR/environment.json" ]; then
    if [ -f "$SOURCE_DIR/config/environment.json" ]; then
        cp $SOURCE_DIR/config/environment.json $CONFIG_DIR/environment.json
        echo "  Configuracao copiada de config/environment.json"
    elif [ -f "$SOURCE_DIR/config/environment.example.json" ]; then
        cp $SOURCE_DIR/config/environment.example.json $CONFIG_DIR/environment.json
        echo "  IMPORTANTE: Edite $CONFIG_DIR/environment.json com os dados do leito"
    else
        echo "  AVISO: Nenhum arquivo de configuracao encontrado"
    fi
else
    echo "  Configuracao ja existe, mantendo..."
fi

# 5. Instala dependencias Python
echo "[5/7] Instalando dependencias Python..."
if [ -f "$INSTALL_DIR/requirements_raspberry.txt" ]; then
    pip3 install -r $INSTALL_DIR/requirements_raspberry.txt
else
    echo "  requirements_raspberry.txt nao encontrado, instalando pacotes essenciais..."
    pip3 install ultralytics opencv-python-headless numpy
fi

# 6. Instala servico systemd
echo "[6/7] Instalando servico systemd..."
cp "$(dirname "$0")/hospital-monitor.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable hospital-monitor
echo "  Servico habilitado para iniciar no boot"

# 7. Configura permissoes
echo "[7/7] Configurando permissoes..."
chown -R pi:pi $INSTALL_DIR
chown -R pi:pi $LOG_DIR
chmod +x $INSTALL_DIR/main.py

# Adiciona usuario pi aos grupos necessarios
usermod -aG gpio pi 2>/dev/null || true
usermod -aG video pi 2>/dev/null || true

echo ""
echo "=============================================="
echo "Instalacao concluida!"
echo "=============================================="
echo ""
echo "Arquivos instalados em: $INSTALL_DIR"
echo "Logs em: $LOG_DIR"
echo "Dados em: $DATA_DIR"
echo ""
echo "Proximos passos:"
echo ""
echo "1. Verifique/edite a configuracao do ambiente:"
echo "   sudo nano $CONFIG_DIR/environment.json"
echo ""
echo "2. (Recomendado) Configure o watchdog de hardware:"
echo "   sudo bash $(dirname "$0")/setup-watchdog.sh"
echo ""
echo "3. Inicie o servico:"
echo "   sudo systemctl start hospital-monitor"
echo ""
echo "4. Verifique o status:"
echo "   sudo systemctl status hospital-monitor"
echo ""
echo "5. Veja os logs em tempo real:"
echo "   tail -f $LOG_DIR/service.log"
echo ""
echo "O servico iniciara automaticamente no proximo boot."
