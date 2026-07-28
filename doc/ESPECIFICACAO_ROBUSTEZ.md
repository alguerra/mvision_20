# Especificação de Robustez MVISION — Pré-Piloto Hospitalar

Complementa `AUDITORIA_2026-07.md`. Cada item segue o formato **problema → solução → resultado esperado → critério de aceite**. Itens **P0** estão implementados (julho/2026); **P1** entram nas primeiras semanas do piloto; **P2** durante/pós-piloto.

**Princípios ordenadores:**
1. Nunca perder uma queda real (fail-safe: dúvida escala, não silencia).
2. Nunca "brickar" o dispositivo offline (toda escrita é atômica; todo boot tem fallback).
3. Reduzir falso positivo sem criar janela cega.

---

## FASE P0 — IMPLEMENTADA

### P0.1 Estado ALERTA_PERSISTENTE (fail-safe de alerta)
- **Problema:** queda real produz blur, oclusão e saída do quadro — sinais que cancelavam o próprio alerta (auditoria A1, A4, A5).
- **Solução implementada** (`modules/pose_analyzer.py`):
  - Em RISCO/FORA, ausência de evidência **congela** os scores (nada decai) e, após `FRAMES_TO_LOSE_PATIENT` (15), transiciona para `ALERTA_PERSISTENTE` (nível crítico, GPIO ativo).
  - `ALERTA_PERSISTENTE` só sai com `ALERT_PERSISTENT_SAFE_FRAMES` (10) frames consecutivos de evidência positiva (paciente visível E dentro da cama) ou reset manual (tecla R / restart).
  - `insufficient_data` em estado de alerta não des-escala: conta e escala para persistente.
  - MONITORANDO + sumiço: se a última posição do núcleo do corpo era dentro da cama e sem pose sentada/em pé recente → **oclusão presumida** (permanece MONITORANDO, status "Paciente possivelmente coberto"); só assume cama vazia após `OCCLUSION_EMPTY_TIMEOUT_FRAMES` (300 ≈ 60 s). Caso contrário → RISCO_POTENCIAL.
  - `patient_monitor.py` nunca exibe "Cama Vazia" com alerta ativo.
- **Resultado esperado:** zero quedas silenciadas por perda de sinal; oclusão por cobertor sem alarme falso e sem "Cama Vazia".
- **Aceite:** testes `tests/test_pose_state_machine.py::TestFailSafeAlertLatch` e `TestOcclusionInBed` (passando); cenários V2 e V6 em campo.

### P0.2 Acompanhante sem cegar o sistema
- **Problema:** `person_count>1` desligava toda a análise; sair de ACOMPANHADO zerava o paciente confirmado (A2, A3, A7).
- **Solução implementada** (`main.py`, `modules/pose_analyzer.py`):
  - `_select_patient_index()`: associação leve da pessoa-paciente por contenção do bbox na cama + distância ao centro da cama + bônus de continuidade de centroide (`PATIENT_ASSOC_MAX_JUMP_RATIO=0.25` da diagonal). Sem tracker pesado (custo ~zero de CPU). Retorna `None` se ninguém tem ≥15% de contenção na cama (só passantes) — a FSM trata como ausência de evidência (alertas preservados).
  - ACOMPANHADO virou **flag** (`companion_present`, votação 5-de-7): exibida na UI/log, mas a análise de risco continua sobre o paciente associado. Threshold de RISCO +0.1 com acompanhante (`COMPANION_RISK_ENTER_BOOST`) para compensar erros de associação.
  - Saída do acompanhante mantém `patient_confirmed`; janela multi-pessoa é limpa; EMA de confiança de keypoints é resetado quando a identidade troca (salto de centroide).
  - Rollback: `COMPANION_ANALYSIS_ENABLED=False` (editável no painel) restaura o comportamento legado.
- **Resultado esperado:** queda com visita no quarto alerta em ≤15 s; visita não gera janela cega na saída.
- **Aceite:** `TestCompanionMode` (passando); cenários V3, V4 em campo.

### P0.3 Índice correto pós-NMS + parâmetros explícitos de inferência
- **Problema:** `keep` descartado, análise sempre no índice `[0]` (A6); inferência dependente de defaults do Ultralytics.
- **Solução implementada:** keypoints/conf/bbox lidos do índice real selecionado; `predict(conf=0.20, iou=0.5, imgsz=640, max_det=5, classes=[0])`.
- **Aceite:** `tests/test_detection_pipeline.py::TestNMSIndexes` (passando).

### P0.4 Configuração atômica (anti-brick)
- **Problema:** web reescrevia `config.py` sem atomicidade (C1).
- **Solução implementada:** `config/runtime_config.json` com whitelist (`RUNTIME_EDITABLE_KEYS` em `config.py`); overlay defensivo no fim do `config.py` (JSON ausente/corrompido/tipo errado → defaults, boot garantido); `modules/atomic_io.py::atomic_write_json` (tempfile + fsync + `os.replace`) usado por `config_manager`, `bed_detector` e `web_auth`. `config.py` não é mais escrito por ninguém.
- **Aceite:** JSON truncado → `import config` OK com defaults (testado); valor salvo → lido em processo novo (testado); V9 em campo (10 cortes de energia).

### P0.5 Boot headless confiável
- **Problema:** espera de display 120 s bloqueante sem heartbeat vs `WatchdogSec=90` (C2).
- **Solução implementada:** espera fatiada em ciclos de 5 s com `send_heartbeat()` a cada fatia e entre cargas de modelo/validações.
- **Aceite:** V10 — boot sem HDMI: `active (running)` em <5 min, zero restarts no journal.

### P0.6 Orçamento de memória
- **Problema:** três modelos residentes sob 768 MB → OOM (C3).
- **Solução implementada:** `BedDetector.ensure_model_loaded()/release_model()` — yolov8l só existe em memória durante calibração/recheck; ASETO removido do runtime; `MemoryHigh=640M` no unit (throttle antes do kill).
- **Aceite:** V14 (soak 72 h) — zero eventos OOM em `journalctl -k`, RSS estável (<5% de crescimento/dia).

### P0.7 Validação offline de modelos
- **Problema:** ponteiro Git LFS → tentativa de download online (C4).
- **Solução implementada:** `validate_model_file()` (existência, magic bytes PK/pickle, rejeição de ponteiro LFS, tamanho mínimo) antes de todo `YOLO()`; env `YOLO_OFFLINE/ULTRALYTICS_OFFLINE/YOLO_AUTOINSTALL` no processo e nos units; verificação no `install.sh`.
- **Aceite:** V13 — substituir `.pt` por ponteiro: falha em <10 s com mensagem inequívoca, sem tráfego de rede.

### P0.8 Anti-flapping de alertas
- **Problema:** transições no mesmo segundo, FIFO de imagens esvaziada, log poluído (B1).
- **Solução implementada:** dwell de publicação de 3 frames (`STATE_PUBLISH_DWELL_FRAMES`) para log/UI — alertas críticos (FORA, PERSISTENTE) publicam imediatamente; GPIO lê o estado bruto (sem atraso); cooldown de imagem de 30 s por par (from,to) (`ALERT_IMAGE_COOLDOWN_SECONDS`); transições consecutivas de alerta agrupadas por `episodio=N` no log.
- **Aceite:** `TestPublication` (passando); V12 — ator oscilando na beirada 2 min: ≤3 transições logadas, imagens antigas preservadas.

### P0.9 Higiene de produção
- Flags DEV só por env (`MVISION_DEV=1`, `MVISION_SKIP_BED=1`) — nunca commitadas ligadas.
- journald limitado (`SystemMaxUse=200M`, drop-in criado pelo `install.sh`).
- GPIO: `stop_risk_alert` não-bloqueante e idempotente; LED pisca no máx. 30 s por episódio (episódio = permanência em alerta), thread única por geração.
- Senha web: PBKDF2-HMAC-SHA256 com salt (100k iterações), migração automática do hash legado no primeiro login, `must_change_password` exposto no login enquanto a senha de fábrica estiver ativa, senha nova ≠ padrão.
- Sudoers NOPASSWD para o botão de restart criado pelo `install-web.sh`.
- IP local sem referência a `8.8.8.8`.

---

## FASE P1 — PRIMEIRAS 2 SEMANAS DE PILOTO

| Item | Problema | Solução proposta | Aceite |
|------|----------|------------------|--------|
| **P1.1 Escalonamento temporal** | Alerta longo parece evento único antigo | RISCO >60 s sem resolução → re-log com `escalated=True` + padrão GPIO distinto; FORA/PERSISTENTE re-logam a cada 60 s | Simulação com relógio mockado |
| **P1.2 Limpeza de código morto** | Painel edita chaves sem efeito; 2 FSMs mortas confundem manutenção (C14) | Remover `StateMachine`/`PoseStateMachine` legadas, buffers órfãos, `EMA_THRESHOLD_PATIENT_LOST`; consumir `is_lying` como reforço de `signal_safe` | grep sem referências; painel só exibe chaves com efeito |
| **P1.3 Ajustes IR e geometria** | 0.7 alto para IR (B2); overlap/containment inconsistentes (B5); cama na borda do frame (B4) | Calibrar `POSE_CONFIDENCE_HIGH` (0.5-0.6) com gravações IR reais (já editável no painel); unificar zona da cama numa única função com clamp e aviso; validação na calibração alerta cama encostada na borda | ≥95% dos frames noturnos com `points_monitored>0`; aviso visível no painel |
| **P1.4 UI de oclusão** | Status de oclusão presumida só no monitor local | Expor `occlusion_presumed` e estado da FSM no backend web (endpoint `/api/status` lendo arquivo de estado) | Painel mostra "possivelmente coberto" em V6 |
| **P1.5 Watchdog do mvision-web** | uvicorn travado não reinicia | Healthcheck HTTP via systemd timer (`curl -f localhost:8080/api/health \|\| systemctl restart mvision-web`) | Matar o event loop → recuperação <2 min |
| **P1.6 Relógio offline** | Timestamps errados pós-reboot (C11) | RTC DS3231 (I2C, ~R$15) + `hwclock` no boot — recomendação forte para dispositivo clínico; fallback `fake-hwclock` + campo `clock_synced` no log | Reboot sem rede → timestamps ±2 s |
| **P1.7 Dinâmica de queda (shadow)** | Sem velocidade/trajetória (A8) | Velocidade vertical do quadril/pescoço normalizada pela altura do bbox; queda = deslocamento >0.5×bbox em <1 s + bbox horizontalizado → boost no `signal_out`. Rodar em **modo shadow** (loga score, não alerta) durante o piloto; ativar após análise | ≥80% das quedas encenadas detectadas pelo score antes do sinal geométrico; 0 disparos em 72 h sem queda |
| **P1.8 Troca obrigatória de senha na UI** | Backend já sinaliza `must_change_password`; frontend não força | Rebuild do frontend com redirect para troca de senha quando a flag vier no login | Login com senha padrão → tela de troca obrigatória |

## FASE P2 — DURANTE/PÓS-PILOTO

| Item | Ganho esperado | Observações |
|------|----------------|-------------|
| **P2.1 Renderização condicional headless** | 15-25% de CPU | `draw_*`/`render` só com display real; anotações compostas on-demand ao salvar imagem de alerta |
| **P2.2 Export NCNN do yolov8n-pose** | 2-4× FPS (3-5 → 8-15) | Export offline no dev, artefato commitado, validar paridade de keypoints (diff médio <2 px em 100 frames) antes de trocar; fallback `.pt` por config |
| **P2.3 CLAHE sob demanda** | CPU do pré-processamento | CLAHE só em cena escura (checagem 1×/s) e/ou ROI da cama; eliminar `frame.copy()` por frame (usado só no recheck) |
| **P2.4 Telemetria `/health`** | Visibilidade de degradação | FPS efetivo, RSS, `vcgencmd get_throttled`, latência de inferência a cada 60 s; alerta no painel se FPS<2 |
| **P2.5 TLS + hardening web** | Segurança de rede | Certificado autoassinado no install, rate-limit de login, cookie `secure` |

---

## PLANO DE VALIDAÇÃO PRÉ-HOSPITAL (V1–V14)

Executar com atores em quarto simulado, após P0 (feito) e antes da instalação. Gravar vídeo + `journalctl` + `alerts.log` de cada cenário. **Critério global: zero quedas encenadas sem alerta.**

| # | Cenário | Procedimento | Resultado esperado |
|---|---------|--------------|--------------------|
| V1 | Queda clássica | Deitar 5 min, rolar para fora até o chão | RISCO→FORA ≤10 s, 1 episódio no log, GPIO ativo |
| V2 | Queda + fuga do quadro | Cair e rastejar para fora do enquadramento | `ALERTA_PERSISTENTE` mantido indefinidamente até evidência segura ou reset |
| V3 | Queda com acompanhante | Acompanhante na poltrona; paciente cai | Alerta ≤15 s com `person_count=2` |
| V4 | Acompanhante interage | Debruçar sobre a cama, ajeitar travesseiro, 2 min | Zero alertas; flag ACOMPANHADO exibida |
| V5 | Passante | Atravessar o quarto (cama vazia e com paciente) | Zero alertas; estado inalterado |
| V6 | Oclusão por cobertor | Cobrir totalmente 10 min; descobrir | Nunca "Cama Vazia"; sem alerta falso; volta a MONITORANDO |
| V7 | Saída legítima | Sentar, levantar, sair andando | RISCO→FORA (enfermagem confirma que quer ser avisada) |
| V8 | Retorno | Voltar e deitar | Alerta cessa; MONITORANDO ≤30 s sem intervenção |
| V9 | Corte de energia | Puxar a tomada 10× (incluindo durante gravação de config no painel) | Boot limpo <5 min todas as vezes; config íntegra ou defaults |
| V10 | Boot headless | Boot sem HDMI e sem rede | `active (running)`, zero restart-loops |
| V11 | Câmera desconectada | Puxar USB em operação; reconectar após 2 min | Recuperação automática; alerta ativo NÃO é silenciado durante a falha |
| V12 | Flapping | Oscilar na beirada da cama 2 min | ≤3 transições logadas; imagens antigas preservadas |
| V13 | Modelo corrompido | Substituir `.pt` por ponteiro LFS | Falha <10 s, mensagem clara, zero tráfego de rede |
| V14 | **Soak 72 h** | Ciclos dia/noite IR; ator executa V1/V4/V7 2×/dia | Zero OOM, zero restarts não planejados, RSS/FPS estáveis, SD com espaço, 100% dos eventos encenados detectados, FP ≤ limite acordado com a enfermagem (sugestão: ≤2/dia) |

**Gate de entrada no hospital:** V1–V3, V9, V10, V13 e V14 100% aprovados; V4–V6 e V12 com taxa de falsos positivos formalmente acordada com a equipe clínica.

## ROADMAP SUGERIDO (~3 semanas até o gate)

- **Semana 1:** validação em bancada dos P0 (V1–V13 em quarto simulado); ajustes finos de thresholds com gravações IR reais (P1.3).
- **Semana 2:** P1.1, P1.2, P1.5, P1.6 (instalar RTC), P1.8; iniciar V14 (soak 72 h) com P1.7 em shadow.
- **Semana 3:** análise do soak + logs do shadow; correções finais; gate formal com a equipe clínica; instalação no hospital.

## HARDENING ADICIONAL (revisão pós-P0)

Itens identificados na revisão final de fragilidades. Os três primeiros estão **implementados**; o overlayroot fica documentado como passo de imagem do sistema.

### Implementados
1. **`data/` fora do git** — imagens de alerta, logs e `bed_reference.json` eram versionados; qualquer mudança em campo travava o `git pull` do deploy. Agora `data/`, `config/runtime_config.json` e `config/web_auth.json` estão no `.gitignore` e fora do índice. **Migração no RPi (uma única vez):** antes do primeiro pull desta versão, preserve a calibração: `cp data/bed_reference.json /tmp/ && git checkout -- data/ && git pull && cp /tmp/bed_reference.json data/`.
2. **Watchdog de hardware** — `install.sh` cria `/etc/systemd/system.conf.d/mvision-watchdog.conf` com `RuntimeWatchdogSec=15` (chip `bcm2835_wdt`): kernel panic ou travamento do systemd reinicia o Pi sozinho. Efetivo após reboot.
3. **Heartbeat visível no painel (anti-falha-silenciosa)** — o monitor publica `/tmp/mvision_status.json` (tmpfs, zero desgaste de SD) a cada 30 s com estado e contagem de pessoas. O backend web cruza isso com o systemd: serviço "active" mas sem sinal >90 s aparece como **"ATENCAO: SEM SINAL do monitor ha Xs"** no status existente do painel, e o endpoint `GET /api/monitor/status` expõe o estado ao vivo (para o frontend P1.4 e para checagens via `curl`).

### Documentado (aplicar na imagem do sistema, com teste dedicado no RPi)
4. **Raiz somente-leitura com overlayroot** — a proteção física definitiva contra corrupção de filesystem por corte de energia (as escritas do MVISION já são atômicas, mas o ext4 do SO não é imune). Procedimento sugerido (Raspberry Pi OS Bookworm):
   1. `sudo apt install overlayroot` (com internet, antes do envio ao hospital);
   2. mover `data/` e `config/` para uma partição gravável dedicada (ex: `/dev/mmcblk0p3` montada em `/mvision-data`) e criar symlinks `/mvision/data → /mvision-data/data` e `/mvision/config → /mvision-data/config`;
   3. habilitar com `overlayroot="tmpfs"` em `/etc/overlayroot.conf`;
   4. para manutenção/atualização: `sudo overlayroot-chroot` (ou desabilitar, atualizar, reabilitar);
   5. validar V9 (cortes de energia) novamente com o overlay ativo.
   Complementos de hardware recomendados: cartão SD industrial (ex: SanDisk High Endurance), fonte oficial 27 W e dissipador ativo (o `CPUQuota=90%` contínuo em ambiente quente causa throttling — que degrada o FPS e alonga todas as janelas da FSM, que são contadas em frames).

## COMO OPERAR AS NOVAS PROTEÇÕES

- **Modo desenvolvimento:** `MVISION_DEV=1 python main.py` (imagens de evidência); `MVISION_SKIP_BED=1` (pular calibração). Em produção, nenhum dos dois é definido.
- **Rollback do modo acompanhante:** painel admin → `COMPANION_ANALYSIS_ENABLED=false` → reiniciar serviço.
- **Sair de ALERTA_PERSISTENTE manualmente:** tecla R no monitor local, ou restart do serviço (`sudo systemctl restart hospital-monitor`).
- **Testes de regressão:** `python -m unittest tests.test_pose_state_machine tests.test_detection_pipeline` (roda em qualquer PC, sem câmera).
