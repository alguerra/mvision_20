# MVISION — Instalação e Atualização

Guia de entrada para instalar e atualizar o sistema. Os detalhes de cada fluxo estão nos documentos em `doc/`.

O sistema opera **100% offline** no hospital: nenhum passo em campo depende de internet.

---

## 1. Instalação em HOSPITAL (técnico de campo)

O técnico **não instala software** — ele grava a imagem pronta e liga o aparelho.

| Passo | O quê | Referência |
|---|---|---|
| 1 | Gravar o cartão SD com a **imagem dourada** (`mvision-vX.Y.img.gz`) usando o Raspberry Pi Imager ("Use custom image") — ou receber o kit com SD já gravado | [`doc/IMAGEM_DOURADA.md`](doc/IMAGEM_DOURADA.md) §5 |
| 2 | No leito: posicionar câmera, ligar, aguardar até 5 min (o aparelho se auto-configura e reinicia sozinho no primeiro boot) | [`doc/CHECKLIST_TECNICO.md`](doc/CHECKLIST_TECNICO.md) |
| 3 | Abrir o painel `http://<ip>:8080`, trocar a senha (obrigatório), identificar o leito, calibrar com a **cama vazia** e conferir "Monitor ativo" | [`doc/CHECKLIST_TECNICO.md`](doc/CHECKLIST_TECNICO.md) |

Diagnóstico em caso de problema (suporte com terminal): `mvision-doctor` — imprime PASS/FALHA por item, em português.

## 2. Construção da imagem dourada (LABORATÓRIO, uma vez por release)

Com internet, num Pi de bancada:

```bash
sudo apt update && sudo apt install -y git git-lfs
git clone <repositorio> /mvision
cd /mvision && git lfs pull          # obrigatório: baixa os modelos .pt reais
sudo bash deploy/install.sh          # deve terminar em "INSTALACAO OK"
# hardening da imagem: overlayroot + RTC (ver doc/IMAGEM_DOURADA.md §3)
sudo bash deploy/install.sh --prepare-image   # sela o SD (limpa segredos)
sudo poweroff                        # remover o SD SEM religar e extrair a imagem
```

Processo completo (extração com pishrink, versionamento, produção de unidades): [`doc/IMAGEM_DOURADA.md`](doc/IMAGEM_DOURADA.md).

## 3. Instalação manual (LABORATÓRIO / desenvolvimento)

Para bancada, sem imagem dourada:

```bash
cd /mvision
sudo bash deploy/install.sh
```

O instalador é **idempotente** — pode ser executado quantas vezes for preciso; cada etapa verifica o estado atual e só age no que falta. Ele instala/configura: os dois serviços (`hospital-monitor`, `mvision-web`), watchdog de hardware, limite do journald, sudoers do painel, display headless, `mvision-doctor`, o atualizador USB e termina com a verificação completa. Se terminar com `INSTALACAO COM PROBLEMAS`, corrija as linhas `[ERRO]` e rode de novo.

> Os antigos `install-web.sh` e `setup-display.sh` foram consolidados no `install.sh` (permanecem como atalhos). Guia manual completo de bancada (SO, SSH, Tailscale de laboratório): [`doc/INSTALACAO_RASPBERRY_PI.md`](doc/INSTALACAO_RASPBERRY_PI.md).

## 4. Atualização

### Em campo (sem rede, sem terminal) — pendrive

No laboratório, gere o pacote:

```bash
tar czf mvision-update-vX.Y.tar.gz --exclude-vcs --exclude=data .
sha256sum mvision-update-vX.Y.tar.gz > mvision-update-vX.Y.tar.gz.sha256
```

Copie os **dois** arquivos para a raiz de um pendrive (FAT32). No leito:

**desligar da tomada → espetar o pendrive → ligar → aguardar o painel voltar (~5 min) → remover o pendrive.**

O sistema valida o checksum, faz backup do código atual, aplica, roda o instalador e registra em `/var/log/mvision-usb-update.log`. Pendrive esquecido no aparelho não re-aplica a mesma versão.

### Em laboratório (com git)

```bash
cd /mvision
bash sync_code.sh            # git fetch + reset para origin/main
sudo bash deploy/update.sh   # reinicia AMBOS os serviços e roda o mvision-doctor
```

> Importante: sempre reiniciar **os dois** serviços após atualizar código — `deploy/update.sh` já faz isso.

## 5. Verificação e operação

| Comando | Para quê |
|---|---|
| `mvision-doctor` | Diagnóstico completo (serviços, câmera, modelos, calibração, disco, memória, throttling, relógio, painel, versão) |
| `journalctl -u hospital-monitor -f` | Logs do monitor em tempo real |
| `journalctl -u mvision-web -f` | Logs do painel |
| `sudo systemctl restart hospital-monitor mvision-web` | Reinício manual dos serviços |

Painel web: `http://<ip>:8080` — senha padrão `mvision123` **apenas no primeiro acesso** (troca obrigatória).

Modo desenvolvimento (nunca em produção): `MVISION_DEV=1` (salva imagens de evidência) e `MVISION_SKIP_BED=1` (pula calibração da cama) — apenas via variável de ambiente.

## 6. Requisitos de hardware (produção)

- Raspberry Pi 5 (8 GB recomendado) com case e **cooler ativo**
- Câmera IR compatível (CSI/Picamera2)
- Cartão SD **industrial/high-endurance**, 32 GB+
- Fonte oficial USB-C 27 W
- Recomendado: módulo RTC DS3231 (relógio correto sem rede)
- LEDs de alerta: GPIO 16 (alerta) e GPIO 20 (sistema pronto)
