# Web Notify

Plugin de webhook HTTP para o ShutdownTimer. Envia notificações para qualquer URL quando o timer executa uma ação.

## Instalação

1. Copie a pasta `web_notify/` para `%USERPROFILE%\.shutdown_timer\plugins\`
2. Reinicie o ShutdownTimer ou clique em **Recarregar Plugins**
3. Na aba **🔌 Plugins**, ative o plugin e configure os parâmetros

## Parâmetros

| Parâmetro | Tipo   | Padrão | Descrição |
|-----------|--------|--------|-----------|
| `url`     | texto  | —      | URL do webhook (obrigatória) |
| `method`  | texto  | `POST` | Método HTTP (`GET`, `POST`, `PUT`) |
| `payload` | texto  | JSON padrão | Corpo da requisição (suporta placeholders) |
| `headers` | texto  | `{}` | Headers extras em JSON |
| `timeout` | número | `5` | Timeout em segundos |

## Placeholders no Payload

O campo `payload` aceita variáveis que são substituídas automaticamente:

| Placeholder | Exemplo de valor |
|-------------|-----------------|
| `{event}`   | `shutdown`, `restart`, `sleep` |
| `{action}`  | Descrição da ação |
| `{timestamp}` | `2024-01-15T14:30:00` |
| `{date}`    | `15/01/2024` |
| `{time}`    | `14:30:00` |

## Exemplos de Uso

### Discord (Webhook)
```
URL:     https://discord.com/api/webhooks/SEU_ID/SEU_TOKEN
Payload: {"content": "🔴 PC vai desligar em breve! Evento: {event} às {time}"}
```

### Slack (Incoming Webhook)
```
URL:     https://hooks.slack.com/services/T.../B.../...
Payload: {"text": "ShutdownTimer: *{event}* — {timestamp}"}
```

### ntfy.sh (notificação push gratuita)
```
URL:     https://ntfy.sh/SEU_TOPICO
Method:  POST
Headers: {"Title": "ShutdownTimer", "Priority": "urgent"}
Payload: Desligamento detectado: {event}
```

### IFTTT Webhooks
```
URL:     https://maker.ifttt.com/trigger/{event}/with/key/SEU_KEY
Method:  POST
Payload: {"value1": "{event}", "value2": "{timestamp}", "value3": "{action}"}
```

### Servidor próprio
```
URL:     http://localhost:3000/webhook
Method:  POST
Headers: {"Authorization": "Bearer meu-token-secreto"}
Payload: {"source": "shutdown_timer", "event": "{event}", "ts": "{timestamp}"}
```

## Funções disponíveis

| Função | Tipo | Descrição |
|--------|------|-----------|
| `web_notify.send_webhook` | **ação** | Envia o webhook com os parâmetros configurados |
| `web_notify.notify_shutdown` | ação | Atalho com `event=shutdown` |
| `web_notify.notify_cancel` | ação | Atalho com `event=cancelled` |
| `web_notify.test_webhook` | ação | Envia mensagem de teste |

## Dependências

Nenhuma dependência externa! Usa `urllib.request` da biblioteca padrão do Python.

> **Nota:** O envio é assíncrono — não bloqueia o timer. Verifique os logs do plugin caso não receba a notificação.

## Permissões requeridas

- `network` — para realizar chamadas HTTP
