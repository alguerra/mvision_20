# MVISION — Construção da Imagem Dourada (laboratório)

A **imagem dourada** é o artefato de instalação do MVISION: um SD master com tudo pronto (SO, dependências, código, modelos, serviços, hardening). O técnico em campo apenas grava e liga — zero terminal, zero internet no hospital (ver `CHECKLIST_TECNICO.md`).

Este processo roda **no laboratório, com internet**, uma vez por release.

## 1. Preparar o SD master

1. Gravar **Raspberry Pi OS (64-bit) Desktop** com o Raspberry Pi Imager. Nas configurações do Imager:
   - Hostname: `mvision`
   - Usuário: `tmed` / senha temporária de laboratório
   - SSH habilitado (será usado só no laboratório)
   - Localidade: `America/Sao_Paulo`, teclado `br`
   - **NÃO** configurar WiFi de laboratório que não deva ir para o hospital
2. Boot no Pi de bancada com internet (cabo).

## 2. Instalar o MVISION

O código vai para o Pi **via SSH a partir do notebook** — o dispositivo nunca tem git/credenciais. No notebook (pasta do projeto):

```bash
git archive --format=tar.gz -o mvision.tar.gz HEAD   # garante LF nos scripts
scp mvision.tar.gz yolov8n-pose.pt yolov8l.pt aseto_v3_best.pt tmed@mvision.local:/home/tmed/
```

No Pi:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo mkdir -p /mvision && sudo chown tmed:tmed /mvision
tar xzf ~/mvision.tar.gz -C /mvision
mv ~/*.pt /mvision/ && rm ~/mvision.tar.gz
sudo bash /mvision/deploy/install.sh   # idempotente; termina com "INSTALACAO OK"
```

O instalador cuida de: dependências, serviços, journald 200M, watchdog de hardware, sudoers, display headless, `mvision-doctor`, atualizador USB e verificação final. Se terminar com erro, corrigir e rodar de novo — é seguro repetir.

## 3. Hardening da imagem (uma vez, antes de extrair)

1. **Proteção do SD (overlay + partição de dados)** — agora automatizada pelo `mvision-overlay` (instalado pelo instalador). **No SD master, deixe a proteção DESATIVADA** — a imagem deve ser selada sem overlay; quem ativa é o firstboot de cada unidade clonada, controlado pelo `mvision-firstboot.conf` que o `--prepare-image` grava na partição de boot:
   - `ENABLE_OVERLAY=0` (default): unidades clonadas ficam sem proteção; ativa-se depois por unidade com `sudo mvision-overlay --prepare-data && sudo mvision-overlay --migrate && sudo mvision-overlay --enable`.
   - `ENABLE_OVERLAY=1`: o firstboot reserva a partição de dados (`DATA_SIZE_GB`, default 4), migra `data/`+`config/` e liga o overlay sozinho.
   - **Só mude para 1 depois de revalidar o cenário V9 (cortes de energia) com o overlay ativo.**
   - Estado/diagnóstico: `sudo mvision-overlay --status` e a seção "Protecao do SD card" do `mvision-doctor`.
2. **RTC DS3231** (se o hardware do kit incluir): habilitar I2C (`raspi-config`), `dtoverlay=i2c-rtc,ds3231` no `config.txt`, desabilitar `fake-hwclock`.
3. Conferir `sudo mvision-doctor` → **SISTEMA OPERANTE** (a falha de "referência de cama" é esperada — a calibração é por leito; o aviso "Protecao do SD inativa" é esperado no master).

## 4. Selar e extrair a imagem

```bash
sudo bash /mvision/deploy/install.sh --prepare-image
```

Isso **limpa os segredos e identidades** que não podem ser clonados (senha web, identificação de leito, calibração, logs, journal), habilita o `mvision-firstboot` e manda desligar. Então:

1. `sudo poweroff`, remover o SD **sem religar** (religar consumiria o firstboot no master).
2. No PC de laboratório (Linux):
   ```bash
   sudo dd if=/dev/sdX of=mvision-vX.Y.img bs=4M status=progress
   sudo pishrink.sh -z mvision-vX.Y.img    # https://github.com/Drewsif/PiShrink
   ```
3. Guardar `mvision-vX.Y.img.gz` com a versão anotada — atualize o arquivo `VERSION` na raiz do projeto **antes** de copiar o código: é ele que o instalador grava em `/etc/mvision-version` e o `mvision-doctor` exibe como "Versão instalada" (junto com um hash do conteúdo do código, já que o dispositivo não tem git).

## 5. Produzir unidades

- Gravar `mvision-vX.Y.img.gz` em cada SD com o Raspberry Pi Imager ("Use custom image").
- No **primeiro boot** de cada unidade, o `mvision-firstboot` roda sozinho: expande o filesystem **reservando a partição de dados persistente**, migra `data/`+`config/` para ela, regenera `machine-id` e chaves SSH, limpa segredos, ativa a proteção do SD (se `ENABLE_OVERLAY=1`) e reinicia. Depois disso o aparelho está pronto para o checklist do técnico.

## 6. Atualizações de campo (sem rede)

Gerar o pacote no laboratório:

```bash
cd /caminho/do/projeto
tar czf mvision-update-vX.Y.tar.gz --exclude-vcs --exclude=data .
sha256sum mvision-update-vX.Y.tar.gz > mvision-update-vX.Y.tar.gz.sha256
```

Copiar os DOIS arquivos para a raiz de um pendrive (FAT32). Em campo: desligar → espetar → ligar. O `mvision-usb-update` valida o checksum, faz backup do código atual, aplica, roda o instalador e registra em `/var/log/mvision-usb-update.log`. Pendrive esquecido no aparelho não re-aplica (controle de versão aplicada em `/var/lib/mvision-updates/`). Se a proteção do SD estiver ativa, o atualizador desativa o overlay, aplica no boot seguinte e reativa sozinho — o processo total leva 2 reboots a mais.

## Notas

- **Tailscale/acesso remoto**: apenas em unidades de laboratório — nunca na imagem que vai ao hospital (requisito: offline, sem acesso remoto).
- A doc `INSTALACAO_RASPBERRY_PI.md` permanece como referência de instalação manual/desenvolvimento; o fluxo oficial de campo é imagem dourada + checklist.
