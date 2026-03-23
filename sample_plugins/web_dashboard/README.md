# 🌐 Web Dashboard — ShutdownTimer Plugin

Monitore e controle o ShutdownTimer **remotamente** de qualquer dispositivo na mesma rede Wi-Fi — celular, tablet ou outro PC — via navegador.

---

## ✨ Funcionalidades

| Recurso | Descrição |
|---|---|
| ⏱ **Timer em tempo real** | Exibição com anel de progresso animado e contagem regressiva ao vivo |
| 🎮 **Controle remoto** | Cancelar, pausar/retomar, +X minutos, executar agora |
| 📋 **Histórico do dia** | Últimas ações registradas hoje |
| 🔒 **PIN de segurança** | Protege os controles contra uso não autorizado |
| 🌗 **Tema dark/light** | Dois temas visuais |
| 📱 **Mobile-friendly** | Layout responsivo, funciona bem em telas pequenas |
| ⚡ **Zero dependências extras** | Usa apenas a stdlib do Python (`http.server`) |
| 🔄 **Atualização automática** | Polling configurável via `/api/status` (padrão: 5 s) |

---

## 🚀 Como usar

1. **Instale o plugin** pela aba *Plugins* → *Instalar Pasta* (selecione esta pasta).
2. **Habilite-o** na lista de plugins instalados.
3. O servidor inicia automaticamente. Procure no log:
   ```
   ✅ Servidor iniciado em: http://192.168.1.100:8080
   ```
4. **No celular** (mesma rede Wi-Fi): abra `http://<IP-do-PC>:8080`.

---

## ⚙️ Parâmetros

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `port` | `8080` | Porta HTTP |
| `host` | `0.0.0.0` | Interface (`0.0.0.0` = rede local; `127.0.0.1` = só este PC) |
| `pin` | *(vazio)* | PIN numérico de 4–8 dígitos (deixe vazio para desativar) |
| `allow_control` | `true` | Permite ou bloqueia controles remotos |
| `extend_minutes` | `10` | Minutos adicionados pelo botão "+X min" |
| `refresh_interval` | `5` | Segundos entre atualizações automáticas |
| `show_history` | `true` | Mostra histórico do dia no dashboard |
| `theme` | `dark` | Tema visual: `dark` ou `light` |
| `start_on_load` | `true` | Inicia o servidor ao carregar o plugin |

---

## 🔌 API JSON

### `GET /api/status`
Retorna o estado atual do timer em JSON:

```json
{
  "timer_display": "00:45:23",
  "remaining":     2723,
  "total":         3600,
  "progress_pct":  75.6,
  "running":       true,
  "paused":        false,
  "action":        "shutdown",
  "mode":          "countdown"
}
```

### `POST /api/control`
Envia um comando de controle:

```json
{ "cmd": "extend", "minutes": 10, "pin": "1234" }
```

Comandos disponíveis:

| `cmd` | Descrição | Parâmetros extras |
|---|---|---|
| `cancel` | Cancela o timer | — |
| `pause` | Pausa o timer | — |
| `resume` | Retoma o timer | — |
| `extend` | Adiciona minutos | `minutes` (int) |
| `execute_now` | Executa a ação imediatamente | — |

Resposta de sucesso:
```json
{ "ok": true, "message": "+10 min adicionados" }
```

Resposta de erro:
```json
{ "ok": false, "error": "PIN inválido" }
```

---

## 🔒 Segurança

- Configure um **PIN** para impedir que qualquer pessoa na rede controle seu PC.
- Use `host: 127.0.0.1` para expor o dashboard **somente no PC local** (sem acesso remoto).
- O plugin **não usa HTTPS**; não exponha a porta ao internet pública.

---

## 📦 Dependências

Nenhuma! O plugin usa exclusivamente a biblioteca padrão do Python:

- `http.server` — servidor HTTP
- `json`, `socket`, `threading`, `hashlib` — utilitários stdlib

---

## 📱 Cenário de uso

```
💻 PC: Timer configurado para desligar em 1 hora

📱 Celular (Wi-Fi):
  Abre: http://192.168.1.100:8080
  Vê:   "Desligar em 45:12"
  Clica: "+10 min"
  Timer estendido para 55:12! ✅
```
