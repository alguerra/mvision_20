# MVISION — Checklist de Instalação no Leito (Técnico)

> **Uma página. Sem terminal. Sem internet.**
> Pré-requisito: cartão SD gravado com a **imagem dourada MVISION** (fornecida pelo laboratório) ou kit já montado com SD instalado.

## Material do kit

- [ ] Raspberry Pi 5 no case com cooler
- [ ] Cartão SD com a imagem MVISION (já inserido)
- [ ] Câmera IR com cabo flat conectado
- [ ] Fonte oficial USB-C 27 W
- [ ] Suporte de fixação da câmera
- [ ] (Se aplicável) LEDs de alerta já cabeados no GPIO

## Passo a passo

**1. Posicionar a câmera**
- Fixar apontando para a cama, enquadrando a cama INTEIRA com folga nas laterais.
- A cama não pode encostar nas bordas da imagem (o sistema avisa se isso ocorrer na calibração).

**2. Ligar**
- Conferir o cabo flat da câmera (travado nas duas pontas).
- Conectar a fonte na tomada. Aguardar **até 5 minutos** no primeiro boot (o aparelho se auto-configura e reinicia sozinho uma vez).

**3. Conectar ao painel**
- No celular/notebook, conectar na rede local indicada pela equipe (ou cabo de rede).
- Abrir o navegador em: `http://<IP-do-aparelho>:8080` (o IP é informado pela equipe de rede ou etiquetado no aparelho).
- Senha inicial: `mvision123` → **o sistema exigirá criar uma senha nova**. Anotar a senha no formulário de instalação.

**4. Identificar o leito**
- No painel: **Configurações** → preencher Hospital, Setor e Leito → Salvar.

**5. Calibrar a cama (cama VAZIA)**
- A cama deve estar vazia, arrumada, sem pessoas ao lado.
- Painel → aguardar o status indicar calibração concluída (ou seguir a tela de calibração, quando disponível).
- Conferir no painel que o retângulo desenhado cobre a cama — **não** a poltrona.

**6. Conferir funcionamento**
- No painel, o status do serviço deve mostrar **"Monitor ativo"** (não pode aparecer "SEM SINAL").
- Pedir para alguém deitar na cama: o estado deve mudar para MONITORANDO em ~30 s.
- A pessoa senta na beirada: deve aparecer RISCO em segundos. Levanta e sai: PACIENTE_FORA + LED de alerta.

**7. Finalizar**
- Preencher o formulário de instalação (leito, IP, senha, data, foto do enquadramento).
- Remover monitor/teclado se usados. Deixar apenas câmera + fonte.

## Se algo der errado

| Sintoma | Ação |
|---|---|
| Painel não abre | Conferir IP com a equipe de rede; aguardar 5 min; tirar da tomada e ligar de novo |
| "SEM SINAL do monitor" no painel | Conferir cabo flat da câmera; religar o aparelho; persiste → acionar suporte |
| Retângulo da calibração no lugar errado | Refazer com a cama vazia e iluminação normal; persiste → acionar suporte |
| Qualquer outro problema | Ligar para o suporte e informar EXATAMENTE a mensagem da tela |

> **Suporte (com acesso ao terminal):** o comando `mvision-doctor` imprime o diagnóstico completo em português — informe as linhas `[FALHA]` ao laboratório.

**Atualização em campo (quando o laboratório enviar um pendrive):** desligar da tomada → espetar o pendrive → ligar → aguardar o painel voltar (~5 min) → remover o pendrive. Nada mais.
