# Discord Busy

Pausa o timer do ShutdownTimer enquanto você está em chamada de voz/vídeo no Discord.

## Como funciona

O plugin usa **três estratégias** de detecção em cascata:

1. **Conexões UDP** — Discord em chamada VoIP abre conexões UDP ativas. É a detecção mais confiável sem permissões especiais.
2. **Discord IPC** — Tenta conectar ao pipe local do Discord para confirmar atividade de RPC.
3. **Modo conservador** — Se `also_check_muted = true`, pausa sempre que o Discord estiver aberto.

## Configuração

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `also_check_muted` | bool | `false` | Se `true`, pausa mesmo sem chamada ativa (quando Discord está aberto) |

## Permissões

- `process_list` — lê processos e conexões de rede via psutil
