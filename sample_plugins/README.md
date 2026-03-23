# Plugins de Exemplo — ShutdownTimer v5.0

## Como instalar

Cada subpasta aqui é um plugin pronto. Você tem **duas formas** de instalar:

### Opção 1 — Copiar a pasta manualmente
Copie a pasta do plugin (ex: `battery_guard/`) para:
```
C:\Users\<seu_usuario>\.shutdown_timer\plugins\
```

### Opção 2 — Pela interface do app
1. Abra o ShutdownTimer → aba **🔌 Plugins**
2. Clique em **📂 Instalar ZIP**
3. Selecione o arquivo `.zip` correspondente (veja abaixo como gerar)

### Como gerar .zip de um plugin
No terminal, dentro da pasta `sample_plugins/`:
```powershell
Compress-Archive -Path battery_guard -DestinationPath battery_guard.zip
```

---

## Plugins disponíveis

| Plugin | Descrição | Permissões |
|--------|-----------|-----------|
| `battery_guard` | Pausa timer quando bateria < X% | process_list |
| `temperature_watch` | Pausa se CPU > temperatura limite | process_list |
| `discord_busy` | Pausa durante chamada de voz no Discord | process_list |
| `work_hours` | Bloqueia ações fora do horário de trabalho | — |
| `web_notify` | Envia webhook HTTP ao desligar | network, notifications |
| `calendar_sync_plus` | Integração com Outlook/Windows Calendar | filesystem, network |

---

## Estrutura de um plugin

```
meu_plugin/
├── plugin.json   ← manifesto (obrigatório)
├── main.py       ← código principal (obrigatório)
└── README.md     ← documentação (opcional)
```

### plugin.json mínimo
```json
{
    "id":          "meu_plugin",
    "name":        "Meu Plugin",
    "version":     "1.0.0",
    "author":      "Seu Nome",
    "description": "O que o plugin faz",
    "permissions": [],
    "entry":       "main.py",
    "conditions":  [],
    "actions":     []
}
```

### Hooks disponíveis em main.py
```python
def on_load():
    """Chamado quando o plugin é carregado."""
    pass

def on_unload():
    """Chamado quando o plugin é descarregado."""
    pass

# Condições (declaradas em plugin.json → "conditions")
def check_minha_condicao(params: dict) -> tuple[bool, str]:
    """Retorna (condição_atingida, motivo)."""
    return False, ""

# Ações (declaradas em plugin.json → "actions")
def run_minha_acao(params: dict) -> bool:
    """Executa a ação. Retorna True se bem-sucedido."""
    return True
```
