# Battery Guard

Pausa o timer do ShutdownTimer quando a bateria do notebook fica abaixo de um nível configurável.

## Configuração

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `threshold` | int | `20` | Percentual mínimo de bateria (%) |

## Comportamento

- Enquanto o carregador estiver conectado, a condição nunca é ativada
- Quando desconectado e bateria ≤ limiar → condição retorna `True` → timer pausa
- Requer `psutil`: `pip install psutil`

## Permissões

- `process_list` — lê informações de hardware via psutil
