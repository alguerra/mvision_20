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
| **P1.3 Ajustes IR e geometria** ⚙️ PARCIAL (ago/2026) | 0.7 alto para IR (B2); overlap/containment inconsistentes (B5); cama na borda do frame (B4) | ✅ Zona da cama unificada em `modules/bed_zone.py` (FSM, containment, seleção de paciente e desenho no monitor usam a mesma função; o monitor desenha a zona expandida tracejada); ✅ calibração avisa cama encostada na borda (log, tela local e campo `touches_edges` em `bed_reference.json`). Pendente: calibrar `POSE_CONFIDENCE_HIGH` com gravações IR reais; aviso no painel web | ≥95% dos frames noturnos com `points_monitored>0`; aviso visível no painel |
| **P1.4 UI de oclusão** | Status de oclusão presumida só no monitor local | Expor `occlusion_presumed` e estado da FSM no backend web (endpoint `/api/status` lendo arquivo de estado) | Painel mostra "possivelmente coberto" em V6 |
| **P1.5 Watchdog do mvision-web** | uvicorn travado não reinicia | Healthcheck HTTP via systemd timer (`curl -f localhost:8080/api/health \|\| systemctl restart mvision-web`) | Matar o event loop → recuperação <2 min |
| **P1.6 Relógio offline** | Timestamps errados pós-reboot (C11) | RTC DS3231 (I2C, ~R$15) + `hwclock` no boot — recomendação forte para dispositivo clínico; fallback `fake-hwclock` + campo `clock_synced` no log | Reboot sem rede → timestamps ±2 s |
| **P1.7 Dinâmica de queda (shadow)** | Sem velocidade/trajetória (A8) | Velocidade vertical do quadril/pescoço normalizada pela altura do bbox; queda = deslocamento >0.5×bbox em <1 s + bbox horizontalizado → boost no `signal_out`. Rodar em **modo shadow** (loga score, não alerta) durante o piloto; ativar após análise | ≥80% das quedas encenadas detectadas pelo score antes do sinal geométrico; 0 disparos em 72 h sem queda |
| **P1.8 Troca obrigatória de senha na UI** | Backend já sinaliza `must_change_password`; frontend não força | Rebuild do frontend com redirect para troca de senha quando a flag vier no login | Login com senha padrão → tela de troca obrigatória |
| **P1.9 Calibração assistida da cama** | Detecção de cama hospitalar em IR opera no limite (sensibilidade 10 = conf 0.03); risco de calibrar na poltrona; sem confirmação humana | Ver seção dedicada abaixo | Instalação só conclui com bbox aprovado pelo instalador |
| **P1.10 Benchmark IR de detecção de cama** ⚙️ PARCIAL (ago/2026) | Todo o tuning (slider, estratégias, pré-processamentos) é empírico, sem medição | ✅ Escada consertada: slider remapeado (nível 5 = conf base 0.10, nível 10 = 0.03; antes nível 5 dava 0.236 e um aparelho novo não calibrava em IR), estratégia `primary` removida (nunca acrescentava candidato), estratégia vencedora e descartes por área agora logados e gravados; `test_bed_images.py` reproduz o mesmo pré-processamento da produção (`prepare_bed_frames`). Pendente: dataset de 100–200 frames IR reais anotados e medição de acerto por estratégia×conf | Conf escolhida com margem ≥3× sobre o piso; ≥95% de acerto no benchmark |

### P1.9 — Calibração assistida da cama (especificação)

**Contexto.** A detecção da cama hospitalar é o alicerce de toda a geometria de risco — e é o elo mais frágil da cadeia: o COCO não conhece "cama hospitalar" (usa `bed/couch/bench` sobre imagem IR fora do domínio de treino), o leito de teste só detecta com sensibilidade 10 (conf efetiva 0.03, o piso do detector), e um quarto com poltrona de acompanhante pode calibrar no objeto errado. Duas proteções já foram implementadas (jul/2026):

- **Gate do recheck pela FSM** (`main.py`): o recheck de 6 h só executa em `AGUARDANDO` com zero pessoas — nunca com paciente/cobertor distorcendo a cena (diretriz de campo: calibrar com cama vazia). Leito ocupado por dias: o recheck espera.
- **Validação cruzada ASETO** (`modules/bed_detector.py`): o bbox candidato do COCO só é aceito se sobrepõe (IoU ≥ 0.25) uma detecção do ASETO — o modelo fine-tuned tem bbox impreciso, mas sabe o que é uma cama hospitalar; o COCO dá a caixa, o ASETO confirma o objeto. Fail-open: ASETO ausente ou cego → aceita com aviso (a validação não pode travar a calibração). Configurável: `ASETO_VALIDATION_ENABLED` / `ASETO_VALIDATION_MIN_IOU`. Custo: 2 inferências do modelo de 6 MB, apenas na calibração/recheck. *Limitação conhecida:* com o ASETO acertando ~38% no lab e a validação fail-open, a proteção anti-poltrona só atua numa minoria dos frames.

Proteções adicionais implementadas em ago/2026 (sem UI — o passo 4 abaixo já vale para a referência automática):

- **Calibração de boot só com cama vazia** (`main.py::calibrate_bed`): 1 inferência de pose antes de calibrar; com pessoa no quadro o sistema mostra "CAMA OCUPADA" e espera (não conta como tentativa). Se já existe referência salva válida e a ocupação passa de `CALIBRATION_OCCUPIED_FALLBACK_SECONDS` (120 s), usa a referência salva — o leito não fica sem cobertura com paciente presente.
- **Recheck só refina, nunca ratchet** (`main.py::_should_accept_recheck`): aceita apenas IoU ≥ `RECHECK_MIN_IOU` (0.5), área dentro de `RECHECK_AREA_RATIO_RANGE` (0.8–1.25) e confiança não inferior. IoU < `RECHECK_MOVED_IOU` (0.3) gera `WARNING "Cama possivelmente MOVIDA"` no journal e mantém a referência. O critério antigo (`score >= atual`, com score crescendo com a área) só deixava o bbox crescer ao longo dos dias.
- **Recheck vê a mesma imagem da calibração**: ambos usam `prepare_bed_frames` (normalizado + cru), independente da normalização IR sob demanda do loop.
- **Proveniência da referência** (`bed_reference.json`): grava `frame_size`, `flip_horizontal`, `sensitivity`, `detected_strategy`, `touches_edges`. Referência de outra resolução/flip (ex.: copiada do notebook por FileZilla) é rejeitada no boot; referência obtida com outro nível do slider vira só fallback após falhas — **mudar o slider e reiniciar agora recalibra de fato**. Arquivos legados sem os campos continuam aceitos.

**Fluxo proposto (a implementar — UI de aprovação):**

1. **Instalação vira um passo formal do checklist:** câmera posicionada, cama VAZIA, iluminação do quarto em condição noturna (IR ativo) e diurna.
2. O instalador abre o painel web → "Calibração" → o sistema captura frames e roda a detecção multi-estratégia + validação ASETO, exibindo a **foto com o bbox desenhado** e os metadados (estratégia, classe, conf, IoU ASETO, % do frame, aviso se o bbox toca a borda).
3. O instalador **aprova ou rejeita**. Rejeitou → reposicionar câmera/ajustar sensibilidade e repetir. Aprovou → o bbox vira **referência golden** persistida em `bed_reference.json` com campo `approved_by`/`approved_at`.
4. **Rechecks nunca substituem uma referência golden por algo diferente**: só podem refiná-la (IoU ≥ 0.5 com a golden E score superior). Divergência maior → alerta no painel ("cama possivelmente movida — recalibração assistida necessária") em vez de troca silenciosa.
5. A instalação em cada leito do hospital só é dada como concluída com bbox aprovado nas duas condições de luz.

**Backend necessário:** endpoint `POST /api/calibration/run` (dispara captura+detecção via arquivo de comando lido pelo monitor), `GET /api/calibration/preview` (imagem anotada), `POST /api/calibration/approve`. Frontend: tela de calibração (requer rebuild — agrupar com P1.8).

**Aceite:** quarto simulado com poltrona ao lado da cama: calibração automática sem aprovação nunca entra em vigor; bbox aprovado sobrevive a reboot e a rechecks; mover a cama 1 m gera aviso no painel sem troca silenciosa da referência.

## FASE P2 — DURANTE/PÓS-PILOTO

| Item | Ganho esperado | Observações |
|------|----------------|-------------|
| **P2.1 Renderização condicional headless** ✅ IMPLEMENTADO | 15-25% de CPU | Desenho só com display real ou ao salvar evidência (DEV_MODE); `render` não roda em headless. `gui/display.py` + `main.py` |
| **P2.2 Export NCNN do yolov8n-pose** ✅ IMPLEMENTADO (export pendente no notebook) | 2-4× FPS (3-5 → 8-15) | `tools/export_ncnn_pose.py` exporta e valida paridade (média <2 px, reprovação bloqueia); `YOLO_POSE_BACKEND="auto"` usa NCNN se a pasta `yolov8n-pose_ncnn_model/` existir no dispositivo; rollback = apagar a pasta ou `backend="pt"`. Doctor acusa ausência |
| **P2.3 Normalização IR sob demanda** ✅ IMPLEMENTADO | CPU do pré-processamento | Gray-world+CLAHE só quando a cena está escura ou com cast IR (decisão em frame subamostrado, cache de 30 frames, `IR_NORMALIZE_AUTO`); `frame.copy()` só quando o recheck vai rodar |
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

### Instalação de campo (implementado)
- **Instalador consolidado idempotente** (`deploy/install.sh`): substitui install-web.sh/setup-display.sh (mantidos como atalhos); cada etapa verifica o estado antes de agir (seguro repetir); units systemd instalados a partir dos templates do repo (fonte única); tolera ausência de internet; termina com verificação real via `mvision-doctor` — só imprime "INSTALACAO OK" se serviços + heartbeat + câmera + modelos + painel estiverem operantes. Modo `--prepare-image` sela o SD para virar imagem dourada.
- **`mvision-doctor`**: autodiagnóstico PASS/FALHA/AVISO em português (serviços, sinal de vida do monitor, câmera, modelos, calibração, disco, memória, throttling, relógio, watchdog, painel, versão). É o instrumento de suporte por telefone e o critério objetivo de fim de instalação.
- **`mvision-firstboot`**: provisionamento automático de unidade clonada da imagem dourada (expande filesystem, regenera machine-id/chaves SSH, limpa segredos, auto-desabilita).
- **Atualização offline por pendrive** (`mvision-usb-update`, roda no boot antes do monitor): pacote `mvision-update-*.tar.gz` + `.sha256` na raiz do pendrive; valida checksum, faz backup, aplica, roda o instalador; idempotente (não re-aplica a mesma versão).
- **Healthcheck do painel** (timer de 2 min): uvicorn "active" mas sem responder → restart automático (fecha o P1.5).
- Docs: `doc/IMAGEM_DOURADA.md` (build da imagem por release) e `doc/CHECKLIST_TECNICO.md` (1 página, sem terminal).

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
