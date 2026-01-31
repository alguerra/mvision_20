#!/bin/bash
#
# MVision Web Interface Installation Script
# Installs and configures the web configuration interface
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== MVision Web Interface Installation ===${NC}"

# Configuration
MVISION_DIR="/mvision"
SERVICE_USER="tmed"
SERVICE_FILE="mvision-web.service"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Este script deve ser executado como root (sudo)${NC}"
    exit 1
fi

# Check if mvision directory exists
if [ ! -d "$MVISION_DIR" ]; then
    echo -e "${RED}Diretorio $MVISION_DIR nao encontrado${NC}"
    echo "Certifique-se de que o codigo do MVision esta em $MVISION_DIR"
    exit 1
fi

# Check if web backend exists
if [ ! -f "$MVISION_DIR/web/backend/main.py" ]; then
    echo -e "${RED}Backend web nao encontrado em $MVISION_DIR/web/backend/${NC}"
    exit 1
fi

echo -e "${YELLOW}[1/5] Instalando dependencias Python...${NC}"
pip3 install --quiet fastapi uvicorn python-multipart pydantic || {
    echo -e "${RED}Falha ao instalar dependencias Python${NC}"
    exit 1
}
echo -e "${GREEN}Dependencias instaladas${NC}"

echo -e "${YELLOW}[2/5] Verificando usuario $SERVICE_USER...${NC}"
if id "$SERVICE_USER" &>/dev/null; then
    echo -e "${GREEN}Usuario $SERVICE_USER existe${NC}"
else
    echo "Criando usuario $SERVICE_USER..."
    useradd -r -s /bin/false "$SERVICE_USER" || true
fi

echo -e "${YELLOW}[3/5] Configurando permissoes...${NC}"
chown -R "$SERVICE_USER:$SERVICE_USER" "$MVISION_DIR/config" 2>/dev/null || true
chmod 755 "$MVISION_DIR/web/backend"

echo -e "${YELLOW}[4/5] Instalando servico systemd...${NC}"
# Copy service file
cp "$MVISION_DIR/deploy/$SERVICE_FILE" "/etc/systemd/system/"

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable "$SERVICE_FILE"
systemctl restart "$SERVICE_FILE"

echo -e "${YELLOW}[5/5] Verificando status...${NC}"
sleep 2

if systemctl is-active --quiet "$SERVICE_FILE"; then
    echo -e "${GREEN}Servico iniciado com sucesso!${NC}"
else
    echo -e "${RED}Servico nao iniciou corretamente${NC}"
    echo "Verifique os logs com: journalctl -u $SERVICE_FILE -f"
    exit 1
fi

# Get IP address
IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}=== Instalacao concluida ===${NC}"
echo ""
echo "Acesse a interface web em:"
echo -e "  ${YELLOW}http://$IP_ADDR:8080${NC}"
echo ""
echo "Senha padrao: mvision123"
echo ""
echo "Comandos uteis:"
echo "  Ver status:  sudo systemctl status $SERVICE_FILE"
echo "  Ver logs:    sudo journalctl -u $SERVICE_FILE -f"
echo "  Reiniciar:   sudo systemctl restart $SERVICE_FILE"
echo "  Parar:       sudo systemctl stop $SERVICE_FILE"
echo ""
