# Calendar Sync Plus

Plugin de integração com Outlook e Calendário do Windows para o ShutdownTimer. Impede desligamentos durante reuniões e agendas automáticas com base nos eventos da sua agenda.

## Dependências opcionais

| Pacote    | Comando                  | Para quê |
|-----------|--------------------------|----------|
| `pywin32` | `pip install pywin32`    | Integração com Microsoft Outlook |
| *(nenhum)* | —                       | Calendário do Windows (via arquivos .ics — sem dependências) |

> O plugin funciona **sem dependências externas** para o Calendário do Windows. O Outlook requer `pywin32`.

## Instalação

1. Copie a pasta `calendar_sync_plus/` para `%USERPROFILE%\.shutdown_timer\plugins\`
2. (Opcional) Instale `pywin32` para suporte ao Outlook: `pip install pywin32`
3. Reinicie o ShutdownTimer
4. Na aba **🔌 Plugins**, ative o plugin e configure as condições

## Conditions disponíveis

### `has_active_event` — Tem evento ativo agora

Bloqueia o desligamento enquanto há uma reunião em andamento.

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `sources` | texto | `outlook,windows` | Fontes: `outlook`, `windows` ou ambos |
| `buffer_before_min` | número | `5` | Minutos **antes** do início do evento para bloquear |
| `buffer_after_min` | número | `0` | Minutos **após** o fim do evento para continuar bloqueando |
| `ignore_keywords` | texto | — | Palavras no título do evento para ignorar (ex: `almoço,lembrete`) |

**Exemplo de uso:**  
*"Não desligue se tiver reunião nos próximos 5 minutos ou durante ela"*

---

### `has_event_in_next_minutes` — Tem evento em breve

Avisa antes do evento começar.

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `sources` | texto | `outlook,windows` | Fontes a verificar |
| `lookahead_min` | número | `30` | Janela de verificação em minutos |
| `ignore_keywords` | texto | — | Palavras no título para ignorar |

---

### `is_free_until_eod` — Sem eventos até o fim do dia

Retorna `True` quando não há mais eventos agendados — ideal para desligar automaticamente após o expediente.

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `sources` | texto | `outlook,windows` | Fontes a verificar |
| `eod_hour` | número | `23` | Hora de corte para "fim do dia" |
| `eod_minute` | número | `59` | Minuto de corte |

**Exemplo de uso:**  
*"Desligue automaticamente quando não houver mais nada na agenda (após 18:00)"*  
Configure `eod_hour=18` e use em conjunto com uma regra de desligamento automático.

## Actions disponíveis

### `log_next_event` — Diagnóstico

Escreve os próximos eventos no log do ShutdownTimer. Use para confirmar se o plugin está lendo sua agenda corretamente.

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `sources` | texto | `outlook,windows` | Fontes a verificar |
| `lookahead_min` | número | `120` | Quantos minutos adiante verificar |

## Fontes suportadas

### 📧 Microsoft Outlook
- Lê o calendário padrão via `win32com` (COM automation)
- Inclui eventos recorrentes
- Requer Outlook instalado e `pip install pywin32`

### 📅 Calendário do Windows
- Lê arquivos `.ics` da pasta de dados do app `Windows Communications`
- Funciona sem dependências extras
- Compatível com contas Outlook.com, iCloud, Google (sincronizadas)

## Exemplos de regras

**Bloquear desligamento durante reuniões do Teams:**
```
Condition: has_active_event
sources: outlook,windows
buffer_before_min: 10
ignore_keywords: almoço,birthday,feriado
```

**Desligar automaticamente ao fim do expediente:**
```
Condition: is_free_until_eod
eod_hour: 18
eod_minute: 0
```
*(Use com uma regra de timer configurada para verificar a cada hora após 17h)*

## Permissões requeridas

- `filesystem` — leitura dos arquivos `.ics` do Calendário do Windows
- `network` — acesso COM ao Outlook (comunicação inter-processo local)
