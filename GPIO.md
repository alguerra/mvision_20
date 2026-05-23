# Mapeamento GPIO - MVISION

## Pinos Utilizados

| GPIO (BCM) | Pino Fisico | Funcao         | Comportamento |
|------------|-------------|----------------|---------------|
| 16         | 36          | Alerta de risco | Pisca a cada 0.5s por ate 30s quando paciente esta em RISCO_POTENCIAL ou PACIENTE_FORA. Para quando entra em ACOMPANHADO ou AGUARDANDO. |
| 20         | 38          | Sistema pronto  | Liga (HIGH) quando a calibracao da cama finaliza com sucesso e o monitoramento inicia. Desliga no cleanup. |

## Configuracao

- Modo: BCM (`GPIO.setmode(GPIO.BCM)`)
- Direcao: ambos como `GPIO.OUT`
- Estado inicial: `LOW`
- Auto-deteccao: o sistema detecta automaticamente se esta rodando em um Raspberry Pi. Pode ser forcado via `GPIO_REAL_MODE` em `config.py`.

## Constantes (config.py)

| Constante            | Valor | Descricao                              |
|----------------------|-------|----------------------------------------|
| GPIO_PIN_ALERT       | 16    | Pino do alerta de risco                |
| GPIO_PIN_SYSTEM_READY| 20    | Pino do indicador de sistema pronto    |
| GPIO_BLINK_INTERVAL  | 0.5   | Intervalo do pisca-pisca (segundos)    |
| GPIO_ALERT_DURATION  | 30    | Duracao maxima do alerta (segundos)    |
| GPIO_REAL_MODE       | None  | None=auto, True=forcar real, False=simulado |

## Arquivos Relacionados

- `modules/gpio_alerts.py` - Classe `GPIOAlertManager` com toda a logica de controle
- `config.py` - Constantes de configuracao
- `main.py` - Integracao com o loop principal de deteccao
