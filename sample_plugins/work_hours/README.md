# Work Hours Only

Bloqueia ações automáticas do ShutdownTimer fora do horário de trabalho configurado.

## Condições disponíveis

| ID | Quando retorna `True` |
|----|----------------------|
| `check_outside_work_hours` | Fora do expediente ou fim de semana |
| `check_inside_work_hours` | Dentro do expediente |

## Configuração

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `start_hour` | int | `9` | Hora de início do expediente |
| `start_minute` | int | `0` | Minuto de início |
| `end_hour` | int | `18` | Hora de fim do expediente |
| `end_minute` | int | `0` | Minuto de fim |
| `block_weekends` | bool | `true` | Tratar sábado/domingo como fora do expediente |

## Exemplos de uso

**Bloquear desligamento automático fora do horário:**
Configure no modo Condicional: "Não executar se `work_hours.check_outside_work_hours` for verdadeiro"

**Permitir desligamento automático apenas durante o dia:**
Use `check_inside_work_hours` como condição de habilitação.

## Permissões

Nenhuma — usa apenas `datetime` da biblioteca padrão do Python.
