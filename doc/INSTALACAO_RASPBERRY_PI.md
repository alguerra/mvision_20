# MVisionCare - Guia de Instalação no Raspberry Pi 5

## Sumário

1. [Visão Geral](#visão-geral)
2. [Requisitos de Hardware](#requisitos-de-hardware)
3. [Instalação do Sistema Operacional](#instalação-do-sistema-operacional)
4. [Configuração Inicial do Raspberry Pi](#configuração-inicial-do-raspberry-pi)
5. [Instalação do MVisionCare](#instalação-do-mvisioncare)
6. [Scripts de Deploy](#scripts-de-deploy)
7. [Interface Web de Configuração](#interface-web-de-configuração)
8. [Acesso Remoto com Tailscale](#acesso-remoto-com-tailscale)
9. [Manutenção e Operação](#manutenção-e-operação)
10. [Solução de Problemas](#solução-de-problemas)

---

## Visão Geral

O **MVisionCare** é um sistema de monitoramento de quedas hospitalares que utiliza visão computacional (YOLOv8) para detectar pacientes em situação de risco. O sistema:

- Monitora continuamente o leito do paciente via câmera
- Detecta poses corporais e analisa risco de queda
- Aciona alertas via GPIO (LEDs/buzzer)
- Registra eventos para análise posterior
- Permite configuração remota via interface web

### Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                    Raspberry Pi 5                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │  Picamera2  │  │   YOLOv8    │  │  GPIO Manager   │  │
│  │  (Câmera)   │──│  (IA/Pose)  │──│  (Alertas)      │  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
│         │                │                  │            │
│         └────────────────┼──────────────────┘            │
│                          │                               │
│              ┌───────────┴───────────┐                   │
│              │    Interface Web      │                   │
│              │    (FastAPI:8080)     │                   │
│              └───────────────────────┘                   │
└─────────────────────────────────────────────────────────┘
```

---

## Requisitos de Hardware

### Obrigatórios

| Componente | Especificação | Observações |
|------------|---------------|-------------|
| Raspberry Pi | Model 5 (4GB ou 8GB RAM) | 8GB recomendado para melhor performance |
| Câmera | Raspberry Pi Camera Module 3 | Ou compatível com Picamera2 |
| Cartão SD | 32GB ou superior, Classe 10/A1 | Recomendado: SanDisk Extreme |
| Fonte | USB-C 5V/5A (27W) | Fonte oficial recomendada |
| Cabo Flat | Cabo CSI para câmera | Compatível com Pi 5 |

### Opcionais

| Componente | Especificação | Uso |
|------------|---------------|-----|
| Monitor HDMI | Qualquer resolução | Diagnóstico e configuração |
| Case com cooler | Case oficial Pi 5 | Dissipação térmica |
| LEDs/Buzzer | 3.3V compatíveis | Alertas visuais/sonoros |
| Cabo Ethernet | Cat5e ou superior | Conexão estável |

### Pinagem GPIO (Alertas)

| Pino | GPIO | Função |
|------|------|--------|
| 36 | GPIO 16 | LED de Alerta (pisca em risco) |
| 38 | GPIO 20 | LED Sistema Pronto |
| 39 | GND | Terra comum |

---

## Instalação do Sistema Operacional

### 1. Download do Raspberry Pi Imager

Baixe o Raspberry Pi Imager em: https://www.raspberrypi.com/software/

### 2. Gravação do Sistema

1. Insira o cartão SD no computador
2. Abra o Raspberry Pi Imager
3. Selecione:
   - **Dispositivo**: Raspberry Pi 5
   - **Sistema Operacional**: Raspberry Pi OS (64-bit) - Desktop
   - **Armazenamento**: Seu cartão SD

4. Clique em **Configurações** (ícone de engrenagem) e configure:

   ```
   ☑ Definir hostname: raspberrypi
   ☑ Habilitar SSH (usar autenticação por senha)
   ☑ Definir usuário e senha:
       Usuário: tmed
       Senha: [sua-senha-segura]
   ☑ Configurar WiFi (opcional):
       SSID: [nome-da-rede]
       Senha: [senha-wifi]
       País: BR
   ☑ Definir configurações de localidade:
       Fuso horário: America/Sao_Paulo
       Layout do teclado: br
   ```

5. Clique em **Gravar** e aguarde a conclusão

### 3. Primeiro Boot

1. Insira o cartão SD no Raspberry Pi
2. Conecte a câmera no slot CSI
3. Conecte cabo de rede (recomendado) ou use WiFi
4. Conecte a fonte de alimentação
5. Aguarde o boot completo (LED verde para de piscar)

---

## Configuração Inicial do Raspberry Pi

### 1. Acesso via SSH

```bash
ssh tmed@raspberrypi.local
# Ou use o IP: ssh tmed@192.168.x.x
```

### 2. Atualização do Sistema

```bash
sudo apt update && sudo apt upgrade -y
```

### 3. Configuração da Câmera

```bash
# Verificar se a câmera foi detectada
libcamera-hello --list-cameras

# Teste rápido (mostra preview por 5 segundos)
libcamera-hello -t 5000
```

Se a câmera não for detectada:
```bash
# Abrir configuração do Raspberry Pi
sudo raspi-config

# Navegar para:
# Interface Options -> Legacy Camera -> Disable (usar libcamera)
# Interface Options -> I2C -> Enable
```

### 4. Instalação de Dependências do Sistema

```bash
# Ferramentas de desenvolvimento
sudo apt install -y git python3-pip python3-venv

# Dependências do OpenCV e Picamera2
sudo apt install -y python3-opencv python3-picamera2

# Dependências para GUI
sudo apt install -y python3-pyqt5 libatlas-base-dev
```

### 5. Configuração do Desktop (para GUI funcionar sem monitor)

```bash
sudo raspi-config
```

Navegue para:
- **System Options** → **Boot / Auto Login** → **Desktop Autologin**

Isso garante que o X11 sempre inicie, mesmo sem monitor conectado.

---

## Instalação do MVisionCare

### 1. Criar Estrutura de Diretórios

```bash
# Criar diretório principal
sudo mkdir -p /mvision
sudo chown tmed:tmed /mvision
```

### 2. Clonar Repositório

```bash
cd /mvision
git clone https://github.com/alguerra/mvision_20.git .
```

> **Nota**: O ponto (.) no final clona diretamente em `/mvision` sem criar subpasta.

### 3. Instalar Dependências Python

```bash
cd /mvision
pip3 install --break-system-packages -r requirements_raspberry.txt
```

### 4. Executar Script de Instalação

```bash
cd /mvision/deploy
sudo bash install.sh
```

Este script:
- Cria e configura o serviço systemd
- Define permissões corretas
- Habilita início automático no boot

### 5. Configurar Display Virtual (Recomendado)

Para funcionar sem monitor físico conectado:

```bash
sudo bash /mvision/deploy/setup-display.sh
```

### 6. Instalar Interface Web

```bash
sudo bash /mvision/deploy/install-web.sh
```

### 7. Reiniciar o Sistema

```bash
sudo reboot
```

### 8. Verificar Instalação

Após reiniciar:

```bash
# Status do serviço principal
sudo systemctl status hospital-monitor

# Status da interface web
sudo systemctl status mvision-web

# Logs em tempo real
journalctl -u hospital-monitor -f
```

---

## Scripts de Deploy

### Estrutura da Pasta Deploy

```
deploy/
├── install.sh              # Instalação principal
├── install-web.sh          # Instalação da interface web
├── setup-display.sh        # Configuração de display virtual
├── update.sh               # Atualização após mudanças
├── hospital-monitor.service
└── mvision-web.service
```

### install.sh

**Função**: Instalação principal do sistema de monitoramento.

```bash
sudo bash /mvision/deploy/install.sh
```

**O que faz**:
- Cria serviço systemd `hospital-monitor`
- Configura variáveis de ambiente (DISPLAY, etc.)
- Define limites de recursos (768MB RAM, 90% CPU)
- Configura permissões para GPIO e câmera
- Habilita início automático no boot

### install-web.sh

**Função**: Instalação da interface web de configuração.

```bash
sudo bash /mvision/deploy/install-web.sh
```

**O que faz**:
- Instala dependências (FastAPI, Uvicorn)
- Cria serviço systemd `mvision-web`
- Configura porta 8080

### setup-display.sh

**Função**: Configura o Raspberry Pi para funcionar sem monitor físico.

```bash
sudo bash /mvision/deploy/setup-display.sh
```

**O que faz**:
- Configura `hdmi_force_hotplug=1` no boot
- Define modo de vídeo padrão
- Garante que o X11 sempre inicie

**Importante**: Após executar, é necessário reiniciar (`sudo reboot`).

### update.sh

**Função**: Reinicia o serviço após alterações no código.

```bash
sudo bash /mvision/deploy/update.sh
```

**Quando usar**: Após fazer `git pull` ou modificar arquivos de configuração.

---

## Interface Web de Configuração

### Acesso

```
URL: http://[IP-DO-RASPBERRY]:8080
Senha padrão: mvision123
```

Para descobrir o IP:
```bash
hostname -I
```

### Funcionalidades

#### 1. Identificação do Ambiente

Configure a identificação única do dispositivo:

| Campo | Descrição | Exemplo |
|-------|-----------|---------|
| Hospital | Nome do hospital | Hospital São Lucas |
| Setor | Ala ou setor | UTI Adulto |
| Leito | Número do leito | 101-A |

Esta identificação aparece nos logs e alertas.

#### 2. Configurações do Sistema

| Configuração | Descrição | Valor Padrão |
|--------------|-----------|--------------|
| DEV_MODE | Salva imagens de alertas | True |
| FLIP_HORIZONTAL | Espelha imagem | True |
| BED_RECHECK_INTERVAL_HOURS | Intervalo para recalibrar cama | 6 |

#### 3. Parâmetros de Detecção (EMA)

| Parâmetro | Descrição | Padrão |
|-----------|-----------|--------|
| EMA_ALPHA | Suavização (0.1=lento, 0.5=rápido) | 0.3 |
| EMA_THRESHOLD_ENTER_RISK | Score para entrar em risco | 0.5 |
| EMA_THRESHOLD_EXIT_RISK | Score para sair de risco | 0.3 |

#### 4. Status do Sistema

Visualize em tempo real:
- Status do serviço (ativo/inativo)
- IP do dispositivo
- Informações da plataforma

#### 5. Controle do Serviço

- **Reiniciar serviço**: Aplica novas configurações
- **Ver logs**: Últimas entradas do journal

### Alteração de Senha

1. Acesse a interface web
2. Vá em **Configurações** → **Segurança**
3. Digite a senha atual e a nova senha
4. A nova senha deve ter no mínimo 6 caracteres

---

## Acesso Remoto com Tailscale

O [Tailscale](https://tailscale.com) permite acesso seguro ao Raspberry Pi de qualquer lugar, sem precisar configurar port forwarding ou VPN tradicional.

### 1. Criar Conta Tailscale

1. Acesse https://tailscale.com
2. Crie uma conta (pode usar Google, Microsoft ou GitHub)
3. Anote o nome da sua rede (ex: `seunome.ts.net`)

### 2. Instalar Tailscale no Raspberry Pi

```bash
# Adicionar repositório
curl -fsSL https://tailscale.com/install.sh | sh

# Iniciar e autenticar
sudo tailscale up
```

Será exibido um link para autenticação. Abra-o no navegador e autorize o dispositivo.

### 3. Verificar Conexão

```bash
# Ver status
tailscale status

# Ver IP do Tailscale
tailscale ip -4
```

O IP será algo como `100.x.x.x`.

### 4. Acessar Remotamente

De qualquer dispositivo conectado à mesma conta Tailscale:

```bash
# SSH
ssh tmed@100.x.x.x

# Interface Web
http://100.x.x.x:8080
```

Ou use o nome mágico DNS:
```bash
ssh tmed@raspberrypi.[sua-rede].ts.net
```

### 5. Configurações Recomendadas

#### Habilitar SSH via Tailscale (mais seguro)

```bash
# No Raspberry Pi
sudo tailscale up --ssh
```

Isso permite SSH sem senha usando autenticação Tailscale.

#### Iniciar Automaticamente no Boot

O Tailscale já é configurado para iniciar automaticamente. Verifique:

```bash
sudo systemctl status tailscaled
```

#### Desabilitar Expiração de Chave

No painel admin do Tailscale (https://login.tailscale.com/admin/machines):
1. Encontre o Raspberry Pi
2. Clique em **...** → **Disable key expiry**

Isso evita que o dispositivo desconecte após 90 dias.

### 6. Instalar Tailscale no Computador/Celular

- **Windows/Mac/Linux**: https://tailscale.com/download
- **iOS/Android**: Busque "Tailscale" na loja de apps

Após instalar e logar na mesma conta, você terá acesso direto ao Raspberry Pi.

---

## Manutenção e Operação

### Comandos Úteis

```bash
# Status dos serviços
sudo systemctl status hospital-monitor
sudo systemctl status mvision-web

# Reiniciar serviços
sudo systemctl restart hospital-monitor
sudo systemctl restart mvision-web

# Logs em tempo real
journalctl -u hospital-monitor -f
journalctl -u mvision-web -f

# Logs das últimas 2 horas
journalctl -u hospital-monitor --since "2 hours ago"

# Uso de recursos
htop
free -h
df -h
```

### Atualização do Sistema

```bash
# Atualizar código
cd /mvision
git pull

# Reiniciar serviço
sudo bash deploy/update.sh
```

### Backup da Configuração

Os arquivos de configuração estão em:

```bash
/mvision/config/
├── environment.json    # Identificação do ambiente
└── web_auth.json       # Senha da interface web (hash)

/mvision/data/
├── bed_reference.json  # Calibração da cama
└── logs/               # Logs de alertas
```

Para backup:
```bash
tar -czf mvision-backup-$(date +%Y%m%d).tar.gz /mvision/config /mvision/data
```

### Monitoramento de Temperatura

```bash
# Ver temperatura atual
vcgencmd measure_temp

# Monitorar continuamente
watch -n 1 vcgencmd measure_temp
```

**Temperaturas normais**:
- Ocioso: 40-50°C
- Em uso: 50-70°C
- Crítico: >80°C (throttling ativado)

---

## Solução de Problemas

### Sistema não inicia

```bash
# Verificar status
sudo systemctl status hospital-monitor

# Ver logs de erro
journalctl -u hospital-monitor -n 100 --no-pager
```

**Causas comuns**:
- Câmera não detectada: Verifique cabo e conexão
- Falta de memória: Verifique com `free -h`
- X11 não iniciou: Execute `setup-display.sh` e reinicie

### Câmera não funciona

```bash
# Verificar se câmera é detectada
libcamera-hello --list-cameras

# Testar câmera
libcamera-hello -t 5000
```

**Soluções**:
1. Verifique se o cabo flat está bem conectado
2. Verifique se está no slot correto (CSI do Pi 5)
3. Reinicie o Raspberry Pi

### Interface web não acessível

```bash
# Verificar serviço
sudo systemctl status mvision-web

# Verificar porta
ss -tlnp | grep 8080

# Reiniciar
sudo systemctl restart mvision-web
```

### Alta utilização de CPU/memória

```bash
# Ver processos
htop

# Ver uso do MVision
ps aux | grep python
```

O YOLOv8 usa bastante CPU. Se necessário, ajuste o `FRAME_DELAY_SECONDS` em `config.py` para reduzir FPS.

### Tailscale não conecta

```bash
# Ver status
tailscale status

# Reconectar
sudo tailscale up --reset
```

Se precisar reautenticar:
```bash
sudo tailscale logout
sudo tailscale up
```

---

## Estrutura de Arquivos

```
/mvision/
├── main.py                 # Aplicação principal
├── config.py               # Configurações globais
├── requirements_raspberry.txt
│
├── config/                 # Configurações persistentes
│   ├── environment.json
│   └── web_auth.json
│
├── data/                   # Dados de runtime
│   ├── bed_reference.json
│   ├── logs/
│   └── alert_images/
│
├── deploy/                 # Scripts de instalação
│   ├── install.sh
│   ├── install-web.sh
│   ├── setup-display.sh
│   └── update.sh
│
├── doc/                    # Documentação
│   └── INSTALACAO_RASPBERRY_PI.md
│
├── gui/                    # Interface gráfica
│   └── display.py
│
├── modules/                # Módulos do sistema
│   ├── camera.py
│   ├── bed_detector.py
│   ├── patient_monitor.py
│   ├── pose_analyzer.py
│   ├── gpio_alerts.py
│   └── ...
│
└── web/                    # Interface web
    ├── backend/
    │   ├── main.py
    │   ├── auth.py
    │   └── config_manager.py
    └── frontend/
        └── templates/
```

---

## Suporte

Para problemas ou dúvidas:
1. Verifique os logs: `journalctl -u hospital-monitor -f`
2. Consulte esta documentação
3. Entre em contato com o suporte técnico

---

*Documento atualizado em: Fevereiro 2026*
*Versão do MVisionCare: 2.0*
