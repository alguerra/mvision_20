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

# 1. Cria diretorios
echo "[1/6] Criando diretorios..."
mkdir -p $INSTALL_DIR
mkdir -p $CONFIG_DIR
mkdir -p $LOG_DIR
mkdir -p $DATA_DIR/logs
mkdir -p $DATA_DIR/alert_images

# 2. Copia arquivos
echo "[2/6] Copiando arquivos..."
cp -r ../main.py $INSTALL_DIR/
cp -r ../config.py $INSTALL_DIR/
cp -r ../modules $INSTALL_DIR/
cp -r ../gui $INSTALL_DIR/
cp -r ../requirements_raspberry.txt $INSTALL_DIR/

# 3. Copia configuracao de exemplo
echo "[3/6] Configurando ambiente..."
if [ ! -f "$CONFIG_DIR/environment.json" ]; then
    cp ../config/environment.example.json $CONFIG_DIR/environment.json
    echo "  IMPORTANTE: Edite $CONFIG_DIR/environment.json com os dados do leito"
else
    echo "  Configuracao ja existe, mantendo..."
fi

# 4. Instala dependencias Python
echo "[4/6] Instalando dependencias Python..."
pip3 install -r $INSTALL_DIR/requirements_raspberry.txt

# 5. Instala servico systemd
echo "[5/6] Instalando servico systemd..."
cp hospital-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable hospital-monitor

# 6. Configura permissoes
echo "[6/6] Configurando permissoes..."
chown -R pi:pi $INSTALL_DIR
chown -R pi:pi $LOG_DIR
chmod +x $INSTALL_DIR/main.py

echo ""
echo "=============================================="
echo "Instalacao concluida!"
echo "=============================================="
echo ""
echo "Proximos passos:"
echo "1. Edite a configuracao do ambiente:"
echo "   sudo nano $CONFIG_DIR/environment.json"
echo ""
echo "2. (Opcional) Configure o watchdog de hardware:"
echo "   sudo bash setup-watchdog.sh"
echo ""
echo "3. Inicie o servico:"
echo "   sudo systemctl start hospital-monitor"
echo ""
echo "4. Verifique o status:"
echo "   sudo systemctl status hospital-monitor"
echo ""
echo "5. Veja os logs:"
echo "   tail -f $LOG_DIR/service.log"
echo "   tail -f $DATA_DIR/logs/alerts.log"
