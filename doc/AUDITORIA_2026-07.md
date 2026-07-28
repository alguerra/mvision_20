# Auditoria Técnica MVISION — Julho/2026

**Escopo:** transição de estados, oclusão, identificação de risco, distinção paciente/acompanhante/passante, resiliência offline e performance no Raspberry Pi.
**Contexto:** pós-avaliação de campo, pré-piloto hospitalar (sem acesso remoto, 100% offline).
**Princípio adotado para remediação (decisão de projeto):** *fail-safe* — em dúvida, oclusão ou perda de sinal, **escalar** o alerta, nunca silenciá-lo.

> As referências arquivo:linha refletem o código **antes** das correções desta auditoria (commit `83c2c1c`). Os achados marcados **[CORRIGIDO]** foram tratados na fase P0 (ver `ESPECIFICACAO_ROBUSTEZ.md`).

---

## 1. Metodologia

1. Varredura completa do código em três frentes independentes: máquina de estados/transições, pipeline de detecção/classificação, resiliência/deploy/offline.
2. Validação cruzada dos achados por leitura dirigida dos arquivos críticos.
3. Análise do log real de campo (`data/logs/alerts.log`), que confirmou o padrão de flapping e a sequência `MONITORANDO → ACOMPANHADO → AGUARDANDO`.
4. Desenho do plano de remediação com critérios de aceite testáveis.

## 2. Mapa real da máquina de estados (antes da correção)

A FSM ativa é `PoseStateMachineEMA` (`modules/pose_analyzer.py`). Estados: `AGUARDANDO`, `MONITORANDO`, `RISCO_POTENCIAL`, `PACIENTE_FORA`, `ACOMPANHADO`. Sinais binários por frame suavizados por EMA (α=0.3) contra thresholds com histerese (entrar em risco 0.5 / sair 0.3; entrar em fora 0.55 / sair 0.3; confirmar paciente 0.8).

Problema estrutural: **todas as rotas de "perda de evidência" convergiam para AGUARDANDO** (silencioso):

```
RISCO_POTENCIAL --patient_lost/insufficient_data--> AGUARDANDO   (alerta cancelado!)
PACIENTE_FORA   --patient_lost/insufficient_data--> AGUARDANDO   (alerta cancelado!)
MONITORANDO     --15 frames sem pessoa-----------> AGUARDANDO   ("Cama Vazia")
ACOMPANHADO     --pessoas<=1---------------------> AGUARDANDO   (+10 frames de graça cegos)
qualquer estado --person_count>1-----------------> ACOMPANHADO  (análise DESLIGADA)
```

## 3. Achados

Severidade: **S1** = risco clínico direto (queda não alertada); **S2** = indisponibilidade/brick do dispositivo; **S3** = falso positivo/confiabilidade; **S4** = manutenção/performance.

### 3.1 Segurança clínica (transição de estados)

| # | Sev | Achado | Local | Status |
|---|-----|--------|-------|--------|
| A1 | S1 | Queda real cancela o próprio alerta: `patient_lost` (15 frames sem pessoa) ou `insufficient_data` (keypoints fracos) derrubavam RISCO/FORA para AGUARDANDO. Blur, corpo parcialmente fora do quadro e oclusão — exatamente os sinais de uma queda — silenciavam o sistema. | `pose_analyzer.py:1030,1050` | **[CORRIGIDO]** latch + `ALERTA_PERSISTENTE` |
| A2 | S1 | Com 2+ pessoas o monitoramento desligava por completo: early-return na FSM e `main.py` nem extraía keypoints. Queda com acompanhante no quarto = invisível. | `pose_analyzer.py:812-821`, `main.py:701` | **[CORRIGIDO]** análise contínua com associação pessoa↔cama |
| A3 | S1 | Saída de ACOMPANHADO forçava AGUARDANDO + `patient_confirmed=False` + 10 frames de graça → ~5 s cegos; se o paciente levantasse junto da visita, os sinais eram zerados e nenhum alerta saía. Log de campo confirma o padrão. | `pose_analyzer.py:825-833,909-912` | **[CORRIGIDO]** ACOMPANHADO virou flag; `patient_confirmed` preservado |
| A4 | S1 | Oclusão >3 s (cobertor/equipamento) → `patient_lost` → AGUARDANDO + status literal "Cama Vazia", zerando a proteção no cenário em que ela mais importa. | `pose_analyzer.py:1014`, `patient_monitor.py:48` | **[CORRIGIDO]** oclusão presumida na cama; "Cama Vazia" bloqueado em alerta |
| A5 | S1 | Sem timeout/escalonamento de alerta: RISCO/FORA podiam persistir para sempre ou sumir silenciosamente; paciente caído fora do quadro virava "AGUARDANDO" verde. | `pose_analyzer.py:993-1082` | **[CORRIGIDO]** `ALERTA_PERSISTENTE` só sai com evidência positiva ou reset |
| A6 | S1 | **Bug**: o NMS manual calculava `keep` mas só o `len()` era usado; a análise lia sempre o índice `[0]` do YOLO — keypoints e bbox podiam vir de detecções diferentes/erradas. | `main.py:696-713` | **[CORRIGIDO]** índice real `keep[idx]` usado ponta a ponta |
| A7 | S1 | Zero tracking/associação de identidade: qualquer pessoa sozinha no quarto era assumida como "o paciente" (acompanhante que fica sozinho vira paciente); EMA de confiança de keypoints era global e contaminava entre pessoas. | `main.py:701`, `pose_analyzer.py:202-213` | **[CORRIGIDO]** (parcial) associação por geometria+centroide; reset do EMA em troca de identidade. Tracking pleno = P1 |
| A8 | S3 | Não existe detecção de queda por dinâmica (velocidade/trajetória) — apenas geometria estática por frame. `feature_extractor.py` existe e nunca é chamado. | projeto todo | **P1.7** (modo shadow) |

### 3.2 Falsos positivos / confiabilidade

| # | Sev | Achado | Local | Status |
|---|-----|--------|-------|--------|
| B1 | S3 | Flapping RISCO↔FORA no mesmo segundo (log real 09:52:28); sem dwell, cooldown ou agrupamento; a FIFO de 50 imagens podia ser esvaziada por um único episódio. | `main.py:749-763`, `alert_logger.py` | **[CORRIGIDO]** dwell de publicação + cooldown 30 s + `episode_id` |
| B2 | S3 | `POSE_CONFIDENCE_HIGH=0.7` alto para IR noturno → `points_monitored==0` → `insufficient_data` em cadeia. | `config.py` | **P1.3** (calibrar com gravações reais; agora editável no painel) |
| B3 | S3 | Passante tratado só por heurística standing 2-de-3 + containment, e apenas no estado AGUARDANDO. | `pose_analyzer.py:435-477,906-932` | Mitigado por A7; revisão fina em P1 |
| B4 | S3 | Bed bbox calibrado `[252,306,639,479]` encosta nas bordas do frame 640×480 — zona de queda à direita/abaixo fora do enquadramento; margens expandidas recortadas. Problema de instalação física da câmera. | `data/bed_reference.json` | **P1.3** (aviso no painel + reposicionamento no piloto) |
| B5 | S4 | Geometria inconsistente: `person_bed_overlap` usava a cama crua e `containment` a cama expandida. | `pose_analyzer.py:451-462,541-555` | **P1.3** |
| B6 | S3 | Sensibilidade (slider 1-10) afeta **apenas** a detecção da cama na calibração — zero efeito sobre risco, ao contrário do que o painel sugere. | `bed_detector.py:109-115` | Documentado; painel P1 |

### 3.3 Resiliência / offline / performance

| # | Sev | Achado | Local | Status |
|---|-----|--------|-------|--------|
| C1 | S2 | Painel web reescrevia `config.py` inteiro via regex, sem atomicidade: queda de energia no meio = arquivo truncado = `ImportError` = restart infinito **sem recuperação possível e sem acesso remoto**. | `config_manager.py:138` | **[CORRIGIDO]** `runtime_config.json` + escrita atômica + overlay defensivo |
| C2 | S2 | `WatchdogSec=90` vs espera de display de até 120 s bloqueante sem heartbeat + carga de 3 modelos → loop de restart no boot sem monitor HDMI (cenário de produção). | `main.py:493`, unit systemd | **[CORRIGIDO]** espera fatiada com heartbeat |
| C3 | S2 | yolov8l (87 MB) + ASETO + yolov8n-pose + PyTorch residentes sob `MemoryMax=768M` → OOM-kill previsível com restart a cada 10 s. ASETO era carregado e **nunca usado** nas estratégias. | `main.py:528-538` | **[CORRIGIDO]** lazy-load/unload do yolov8l; ASETO removido; `MemoryHigh=640M` |
| C4 | S2 | Modelos `.pt` em Git LFS sem validação: clone sem `git-lfs` deixa ponteiros de texto; ultralytics tentaria **baixar da internet** (falha fatal offline). | startup | **[CORRIGIDO]** validação de magic bytes + env `YOLO_OFFLINE` + check no install.sh |
| C5 | S2 | journald sem `SystemMaxUse` (default = 10% do SD ≈ 3 GB de escrita contínua). | sistema | **[CORRIGIDO]** drop-in 200M no install.sh |
| C6 | S3 | `DEV_MODE=True` e `DEV_SKIP_BED_DETECTION=True` commitados: produção gravava JPEG por transição (desgaste do SD) e a cama nunca era recalibrada. | `config.py:151,156` | **[CORRIGIDO]** flags só por env `MVISION_DEV`/`MVISION_SKIP_BED` |
| C7 | S3 | GPIO: `stop_risk_alert` com `join(1.0)` chamado a cada frame (podia roubar 1 s/frame); timer de 30 s do LED inoperante (thread recriada a cada frame); risco de threads concorrentes no mesmo pino. | `gpio_alerts.py:100-153` | **[CORRIGIDO]** stop não-bloqueante idempotente + episódio com geração |
| C8 | S3 | Botão "Reiniciar serviço" do painel exigia regra sudoers que nenhum instalador criava → falhava com timeout. | `config_manager.py:222` | **[CORRIGIDO]** drop-in sudoers no install-web.sh |
| C9 | S3 | Senha padrão `mvision123`, SHA-256 sem salt, sessões sem limpeza, HTTP sem TLS em 0.0.0.0:8080. | `auth.py` | **[CORRIGIDO]** (parcial) PBKDF2+salt, migração automática, flag de troca obrigatória; TLS = P2.5 |
| C10 | S3 | Consulta de IP conectava em `8.8.8.8` (referência externa em sistema offline). | `config_manager.py:157` | **[CORRIGIDO]** enumeração local |
| C11 | S3 | Sem NTP/RTC: timestamps errados após reboot offline; rotação diária de log incorreta. | sistema | **P1.6** (RTC DS3231 recomendado) |
| C12 | S4 | Renderização e desenho completos rodando mesmo headless (~15-25% CPU); CLAHE full-frame todo frame; `frame.copy()` 5×/s usado só a cada 6 h; modelo PyTorch fp32 sem export NCNN (2-4× de FPS na mesa). | `display.py`, `main.py` | **P2.1-P2.3** |
| C13 | S4 | Sem telemetria: nenhum FPS efetivo, RSS, temperatura ou latência exposta — degradação em campo é invisível. | sistema | **P2.4** |
| C14 | S4 | Código morto perigoso: 2 FSMs não usadas (`StateMachine`, `PoseStateMachine`), buffers nunca alimentados, `EMA_THRESHOLD_PATIENT_LOST` declarado e nunca lido, `POSE_FRAMES_TO_CONFIRM` editável no painel sem efeito algum. | `state_machine.py`, `pose_analyzer.py` | **P1.2** (limpeza) |

## 4. Pontos únicos de falha (antes das correções, em ordem de severidade)

1. Escrita não-atômica de `config.py` pela web → brick de software irrecuperável offline (C1).
2. OOM-kill por três modelos residentes sob 768 MB (C3).
3. Loop de restart no boot headless por watchdog × espera de display (C2).
4. Ponteiros Git LFS + tentativa de download online (C4).
5. Cancelamento de alerta por perda de evidência (A1) — não derruba o dispositivo, mas derruba a razão de existir do produto.

## 5. Conclusão

O sistema tinha boa base (EMA com histerese, votação majoritária, recuperação de câmera, rotação de logs), mas as rotas de exceção convergiam sistematicamente para o silêncio — o oposto do que um monitor clínico deve fazer — e três defeitos de resiliência podiam tirar o dispositivo do ar sem retorno em ambiente sem acesso remoto. A fase P0 (implementada) inverte o princípio: **ausência de evidência mantém e escala o alerta**, o acompanhante não cega o sistema, e nenhuma escrita de configuração pode impedir o boot. O gate de entrada no hospital está definido no plano de validação V1–V14 da especificação.
