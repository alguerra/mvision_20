# MVISION — Passo a passo: do zero ao sistema operante

Roteiro único e completo. Seguindo as etapas na ordem, ao final você terá o sistema instalado, configurado, calibrado e monitorando o leito. Cada etapa termina com um **✔ Ponto de verificação** — só avance se ele passou.

> A instalação (etapas 1–5) precisa de **internet** e é feita em bancada/laboratório.
> A operação no hospital é **100% offline** — nada em campo depende de rede externa.

---

## O que você vai precisar

- Raspberry Pi 5 (8 GB recomendado) com case e **cooler ativo**
- Câmera IR compatível (CSI/Picamera2) com cabo flat
- Cartão SD 32 GB+ (produção: industrial/high-endurance)
- Fonte oficial USB-C 27 W
- Um computador com leitor de SD e o [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- Rede com internet para a instalação (cabo de preferência)
- Opcional: monitor HDMI + teclado (ou use SSH); módulo RTC DS3231; LEDs nos GPIO 16 (alerta) e 20 (pronto)

---

## Etapa 1 — Gravar o cartão SD

1. Insira o SD no computador e abra o **Raspberry Pi Imager**.
2. Selecione:
   - **Dispositivo:** Raspberry Pi 5
   - **Sistema:** Raspberry Pi OS (**64-bit**) — versão **Desktop**
   - **Armazenamento:** seu cartão SD
3. Clique em **Editar configurações** (engrenagem) e defina:
   - Hostname: `mvision`
   - **Habilitar SSH** (autenticação por senha)
   - Usuário: `tmed` / senha: *(defina e anote)*
   - WiFi (opcional — prefira cabo de rede)
   - Localidade: fuso `America/Sao_Paulo`, teclado `br`
4. Grave e aguarde concluir.

**✔ Ponto de verificação:** o Imager mostrou "gravação concluída com sucesso".

## Etapa 2 — Primeiro boot e acesso

1. Insira o SD no Pi, conecte o **cabo flat da câmera** (travado nas duas pontas), o cabo de rede e por último a fonte.
2. Aguarde ~2 min para o primeiro boot.
3. Acesse o terminal do Pi de uma das formas:
   - **SSH** (recomendado): `ssh tmed@mvision.local` (ou pelo IP — veja no roteador), ou
   - Monitor HDMI + teclado, abrindo o Terminal no desktop.

**✔ Ponto de verificação:** você está num prompt `tmed@mvision:~ $`.

## Etapa 3 — Copiar o código do notebook para o dispositivo

O dispositivo **não usa git** (nenhum login/credencial no aparelho). O código é copiado do seu notebook por SFTP — use o método que preferir.

### Opção A — FileZilla (ou WinSCP)

1. Conecte no dispositivo: host `sftp://mvision.local` (ou o IP), usuário `tmed`, senha definida na Etapa 1, porta 22.
2. No Pi (via SSH), crie a pasta de destino:
   ```bash
   sudo mkdir -p /mvision && sudo chown tmed:tmed /mvision
   ```
3. No FileZilla, arraste o **conteúdo** da pasta do projeto para `/mvision`, **exceto**: `.git/`, `data/`, `teste_camera/` e arquivos `debug_*`. Confirme que os modelos `.pt` foram junto (são os arquivos grandes — 6 MB a 87 MB).
4. **Obrigatório após a cópia** — normalizar fim de linha dos scripts (arquivos vindos do Windows podem ter CRLF, que quebra os `.sh` no Linux):
   ```bash
   find /mvision -type f \( -name '*.sh' -o -name '*.service' -o -name '*.timer' \) -exec sed -i 's/\r$//' {} +
   ```

### Opção B — Pacote + scp (linha de comando)

No notebook (Git Bash, na pasta do projeto):
```bash
git archive --format=tar.gz -o mvision.tar.gz HEAD   # LF garantido nos scripts
scp mvision.tar.gz yolov8n-pose.pt yolov8l.pt aseto_v3_best.pt tmed@mvision.local:/home/tmed/
```
No Pi:
```bash
sudo mkdir -p /mvision && sudo chown tmed:tmed /mvision
tar xzf ~/mvision.tar.gz -C /mvision
mv ~/yolov8n-pose.pt ~/yolov8l.pt ~/aseto_v3_best.pt /mvision/
rm ~/mvision.tar.gz
```
(Os `.pt` vão separados porque o `git archive` exporta apenas os ponteiros LFS.)

**✔ Ponto de verificação (qualquer opção):**
```bash
ls -lh /mvision/main.py /mvision/yolov8n-pose.pt /mvision/yolov8l.pt
head -1 /mvision/deploy/install.sh
```
Os `.pt` devem ter **MB de tamanho** (ex.: 6M e 87M) — não 130 bytes — e a última linha deve mostrar exatamente `#!/bin/bash` (sem `^M` ou caracteres estranhos no final).

## Etapa 4 — Instalar

```bash
cd /mvision
sudo bash deploy/install.sh
```

O instalador é **idempotente**: se algo falhar, corrija o que a linha `[ERRO]` indicar e rode o mesmo comando de novo — ele pula o que já está feito. Ele instala e configura: os serviços `hospital-monitor` e `mvision-web`, watchdog de hardware, limite de logs do sistema, regra do botão de restart do painel, display headless, o diagnóstico `mvision-doctor` e o atualizador por pendrive — e termina rodando a verificação completa.

**✔ Ponto de verificação:** a última seção da saída mostra **`INSTALACAO OK`**.
(Único aviso aceitável nesta fase: "Sem referencia de cama" — a calibração vem na Etapa 6.)

## Etapa 5 — Reiniciar

```bash
sudo reboot
```

Necessário para ativar o watchdog de hardware e o HDMI headless. Aguarde ~3 min (a primeira inicialização carrega os modelos) e confira:

```bash
ssh tmed@mvision.local
mvision-doctor
```

**✔ Ponto de verificação:** `mvision-doctor` termina com **`SISTEMA OPERANTE`** — em especial:
- `[PASS] hospital-monitor ativo` e `[PASS] mvision-web ativo`
- `[PASS] Monitor publicando status ha Xs`
- `[PASS] Camera CSI detectada`

## Etapa 6 — Configurar pelo painel web

1. Descubra o IP: `hostname -I` (primeiro endereço).
2. No navegador de qualquer máquina da mesma rede: `http://<IP>:8080`
3. Entre com a senha padrão **`mvision123`** → o sistema **exigirá criar uma senha nova**. Anote-a.
4. Em **Configurações**, preencha **Hospital, Setor e Leito** → Salvar.
5. Use o botão **Reiniciar serviço** do painel (ou `sudo systemctl restart hospital-monitor`) para aplicar.

**✔ Ponto de verificação:** o painel mostra a identificação do leito e o status **"Monitor ativo"** (nunca "SEM SINAL").

## Etapa 7 — Posicionar a câmera e calibrar a cama

1. Fixe a câmera enquadrando a **cama inteira, com folga nas laterais** — a cama não pode encostar nas bordas da imagem.
2. Deixe a **cama vazia e arrumada**, sem ninguém ao lado, com iluminação normal do quarto.
3. Reinicie o monitor para disparar a calibração:
   ```bash
   sudo systemctl restart hospital-monitor
   ```
4. Acompanhe (opcional): `journalctl -u hospital-monitor -f` — procure a linha `Calibracao OK` com o bbox.
5. Confira no monitor HDMI (se conectado) ou nas imagens do painel que o **retângulo cobre a cama** — não a poltrona.

**✔ Ponto de verificação:**
```bash
mvision-doctor
```
→ `[PASS] Referencia da cama valida: [x1, y1, x2, y2]`

> Se a calibração falhar repetidamente: ajuste o **slider de sensibilidade** no painel (aumentar = mais permissivo), confira o enquadramento e a iluminação, e reinicie o serviço. A calibração fica salva e sobrevive a reboots.

## Etapa 8 — Teste funcional (com uma pessoa)

Peça a alguém para simular o paciente e observe o estado no painel/monitor:

| Ação | Estado esperado | Tempo |
|---|---|---|
| Deitar na cama e ficar parado | `MONITORANDO` | ≤ 30 s |
| Sentar na beirada da cama | `RISCO_POTENCIAL` | segundos |
| Levantar e sair | `PACIENTE_FORA` + LED de alerta piscando | segundos |
| Voltar e deitar | alerta cessa → `MONITORANDO` | ≤ 30 s |
| Segunda pessoa entra no quarto | `ACOMPANHADO` (monitoramento continua) | ~2 s |

**✔ Ponto de verificação:** as cinco linhas da tabela se comportaram como esperado e os eventos aparecem no log de alertas do painel.

**🎉 O sistema está instalado e operante.** Para uso em bancada/piloto supervisionado, terminou aqui.

---

## Etapa 9 (produção em escala) — Selar a imagem dourada

Para instalar em vários leitos sem repetir tudo isso, transforme este SD em imagem master:

```bash
sudo bash /mvision/deploy/install.sh --prepare-image   # limpa segredos e identidade
sudo poweroff                                          # NAO religue este SD antes de clonar
```

No PC de laboratório: extraia (`dd`) e comprima (`pishrink`) a imagem. Cada SD gravado com ela se auto-provisiona no primeiro boot (expande o disco, regenera identidade, reinicia) — o técnico em campo só segue o `doc/CHECKLIST_TECNICO.md` (1 página, sem terminal): ligar, trocar senha, identificar o leito e calibrar. Detalhes: `doc/IMAGEM_DOURADA.md`.

> Antes de produzir a imagem de hospital, aplique também o **overlayroot** (raiz somente-leitura — proteção contra corte de energia) e o **RTC**, conforme `doc/IMAGEM_DOURADA.md` §3.

---

## Atualização do sistema

### Em campo, sem rede (pendrive)

No laboratório:
```bash
cd /mvision
tar czf mvision-update-v1.1.tar.gz --exclude-vcs --exclude=data .
sha256sum mvision-update-v1.1.tar.gz > mvision-update-v1.1.tar.gz.sha256
```
Copie os **dois arquivos** para a raiz de um pendrive (FAT32). No leito:

**desligar da tomada → espetar o pendrive → ligar → aguardar o painel voltar (~5 min) → remover o pendrive.**

O sistema valida o checksum, faz backup, aplica e reinicia sozinho (log em `/var/log/mvision-usb-update.log`). Pendrive esquecido não re-aplica a mesma versão.

### Em bancada, copiando do notebook (sem git no dispositivo)

1. Copie os arquivos alterados para `/mvision` — FileZilla (Opção A da Etapa 3) ou pacote+scp (Opção B). Não copie `.git/`, `data/`, `teste_camera/`.
2. Se usou FileZilla, normalize os fins de linha (mesmo comando `find ... sed` da Etapa 3).
3. Aplique:
   ```bash
   sudo bash /mvision/deploy/update.sh   # reinicia OS DOIS servicos e roda o mvision-doctor
   ```

> Se os modelos `.pt` mudaram, copie-os também. Se scripts de deploy ou units mudaram, rode `sudo bash /mvision/deploy/install.sh` em vez do `update.sh` (é idempotente e reinstala o que mudou).

---

## Se algo der errado

1. **Sempre comece por:** `mvision-doctor` — ele diz exatamente o que está falhando, em português.
2. Logs detalhados: `journalctl -u hospital-monitor -n 100` e `journalctl -u mvision-web -n 50`.
3. Reinstalar/reparar é seguro: `sudo bash /mvision/deploy/install.sh` (idempotente).

| Sintoma | Causa provável | Solução |
|---|---|---|
| `[FALHA] ... ponteiro Git LFS` | os `.pt` reais não foram copiados (foi o ponteiro de texto) | copiar os `.pt` verdadeiros do notebook: `scp *.pt tmed@mvision.local:/mvision/` |
| `bash: /bin/bash^M` ou erro estranho nos scripts | código copiado com CRLF do Windows | rodar o comando de normalização da Etapa 3 (`find ... sed -i 's/\r$//'`) |
| `[FALHA] NENHUMA camera detectada` | cabo flat solto/invertido | reconectar o flat (trava nas duas pontas) e reiniciar |
| Painel não abre | serviço web parado / IP errado | `mvision-doctor`; conferir IP com `hostname -I` |
| "SEM SINAL do monitor" no painel | monitor travado ou câmera falhou | `journalctl -u hospital-monitor -n 100`; religar o aparelho |
| Calibração não conclui | enquadramento/iluminação/sensibilidade | Etapa 7 + slider de sensibilidade no painel |
| Estados oscilando/atrasados | throttling térmico | `mvision-doctor` acusa; conferir cooler e fonte 27 W |

**Modo desenvolvimento** (nunca em produção): `MVISION_DEV=1` (salva imagens de evidência) e `MVISION_SKIP_BED=1` (pula calibração) — somente via variável de ambiente no serviço.

---

*Documentos complementares:* `doc/CHECKLIST_TECNICO.md` (instalação em campo, 1 página) · `doc/IMAGEM_DOURADA.md` (build da imagem por release) · `doc/INSTALACAO_RASPBERRY_PI.md` (referência de bancada) · `doc/ESPECIFICACAO_ROBUSTEZ.md` (especificação técnica e plano de validação).
