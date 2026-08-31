# MVISION — Posicionamento e desenvolvimento futuro

Avaliação de 2026-08-31, comparando o MVISION com o estado da arte mundial em
visão computacional para detecção/prevenção de queda hospitalar.

## Estado da arte (referência)

**Comercial:** Ocuvera (câmera de profundidade 3D, previsão de saída da cama,
silhueta em vez de vídeo para privacidade) e VirtuSense/VSTOne (LiDAR + edge AI,
alerta de saída da cama 31–65s ANTES do evento, integração com fluxo de
enfermagem, ROI documentado 4–5.5x). Padrão comum dos líderes: sensor 3D
proprietário, predição em vez de reação, integração nurse-call, evidência
clínica publicada.

**Acadêmico:** pose 3D + modelos temporais (TCN/GCN/transformers) com ~99% em
benchmarks; destilação de conhecimento para edge. A fronteira é dinâmica
temporal (velocidade/trajetória de keypoints), não postura estática.

Fontes: ocuvera.com/our-solution · virtusense.ai/products/vstalert ·
nature.com/articles/s41598-025-11325-y · arxiv.org/pdf/2401.11790 ·
doi.org/10.1016/j.engappai.2024.109809

## Onde o MVISION está ACIMA

1. **Custo e soberania do dado** — hardware ~R$1.000 (RPi 5 + câmera IR) vs
   sensores proprietários de milhares de dólares; 100% offline = LGPD por
   arquitetura. Vantagem real em hospitais brasileiros/públicos.
2. **Filosofia fail-safe genuína** — "ausência de evidência nunca cancela
   alerta" (latch ALERTA_PERSISTENTE, oclusão presumida, watchdog em 3
   camadas). Mais rigoroso que a academia, que otimiza benchmark e ignora o
   modo de falha silencioso.
3. **Operacionalização em escala** — imagem dourada, firstboot, doctor,
   atualização por pendrive, proteção de SD. Engenharia de deploy que separa
   produto de protótipo.
4. **Tratamento do acompanhante** — seleção de paciente validada (11/11 nos
   alertas reais, ago/2026); papers de fall detection ignoram o cenário
   multi-pessoa.

## Fragilidades e caminhos de evolução

| # | Fragilidade | Evolução | Esforço |
|---|---|---|---|
| 1 | **Reativo, não preditivo** (VSTOne alerta 31–65s antes; MVISION detecta quando já sentou/levantou) | P1.7 já especificado: TCN/GCN leve sobre buffer de keypoints (roda no RPi via NCNN), em shadow mode; medir lead time real do RISCO_POTENCIAL | Médio |
| 2 | **2D sem profundidade** — oclusão por cobertor/acompanhante é o calcanhar de aquiles (confirmado na validação ago/2026) | Curto prazo: fine-tune pose/detector com dados IR hospitalares (exige gravador de frame limpo). Médio prazo: SKU premium com câmera de profundidade (OAK-D/ToF, +US$150) sem mudar arquitetura | Médio/Alto |
| 3 | **Modelos genéricos COCO** — yolov8n-pose nunca viu paciente sob lençol em IR | Cada hospital piloto vira fonte de dataset anotado (frame limpo + anotação); repetir o caminho do ASETO para pose | Médio |
| 4 | **Sem integração assistencial** — GPIO + painel não competem com alerta no bolso da enfermeira | Webhook/MQTT para nurse-call e apps de plantão, mantendo offline (rede local) | Baixo |
| 5 | **Sem evidência clínica** — concorrentes vendem ROI documentado | Piloto LEITO-104 produzir métricas do vocabulário do comprador: quedas/1000 pacientes-dia, falsos alarmes/dia, tempo de resposta (logs já capturam quase tudo) | Baixo |

## Prioridade recomendada

Os 3 investimentos com melhor retorno, em ordem — nenhum muda a arquitetura:

1. **Gravador de frame limpo** junto ao alerta (destrava #2, #3 e replays)
2. **Dataset hospitalar próprio** (IR, paciente deitado, acompanhante)
3. **Modelo temporal em shadow mode** (P1.7) com medição de lead time

## Backlog técnico corrente (validação ago/2026)

- Aviso de "cama > 50% do quadro" na calibração (falha silenciosa por
  BED_MAX_AREA_RATIO com câmera muito próxima) + distância mínima no guia
- Detecções fantasma de "pessoa" em móveis contam em person_count (display
  ACOMPANHADO indevido)
- Revalidar V9 (queda de energia) com overlay ativo; RTC no instalador
- Escalonamento para câmera permanentemente morta (hoje: restart infinito 10s)
