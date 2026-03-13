# ShutdownTimer v3.0

![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

Um agendador inteligente de desligamento com interface gráfica moderna, widget flutuante, monitoramento condicional e suporte completo a linha de comando.

<div align="center">
  <img width="442" height="872" alt="Interface Principal" src="https://github.com/user-attachments/assets/25e17de5-42d5-48b4-8cfb-7a113b3e1e71" />
  <img width="442" height="872" alt="Configurações" src="https://github.com/user-attachments/assets/fff044ae-f7f5-4619-8292-7a454cd71d56" />
  <img width="160" height="48" alt="Widget Flutuante" src="https://github.com/user-attachments/assets/cead8867-21c6-427a-a20c-cb1843615f45" />
</div>

## ✨ Características

### ⏱ Múltiplos modos de agendamento
- Contagem regressiva personalizável
- Horário específico (executa às HH:MM)
- Presets rápidos (15, 30, 60, 120 minutos)

### 🎯 Ações suportadas
- Desligar (shutdown)
- Suspender (sleep)
- Reiniciar (reboot)
- Bloquear tela (lock)

### 🧠 Monitoramento condicional (requer psutil)
- Desligar quando CPU ficar abaixo de X%
- Aguardar processo específico encerrar
- Detectar conclusão de downloads
- Executar após período de inatividade

### 🎮 Modo Gamer inteligente
- Pausa automaticamente durante jogos em tela cheia
- Detecta processos configuráveis (ex: valorant.exe, blender.exe)
- Resume quando você volta

### 📊 Recursos avançados
- Timer adaptativo (estende automaticamente com atividade)
- Histórico completo e estatísticas
- Exportação para CSV/JSON
- Atalhos globais de teclado
- Widget flutuante transparente
- Ícone na bandeja do sistema
- Notificações nativas
- Inicialização automática com o sistema

## 🚀 Instalação

### Pré-requisitos
- Python 3.7 ou superior
- pip (gerenciador de pacotes Python)

### Instalação básica
```bash
# Clone o repositório
git clone https://github.com/rascunho2607/ShutdownTimer.git
cd shutdowntimer

# Instale a dependência obrigatória
pip install customtkinter

# Execute
python shutdown_timer.py
Instalação completa (com todos os recursos)
bash
# Todas as dependências opcionais
pip install customtkinter pystray pillow plyer psutil keyboard
Dependências detalhadas
Pacote	Obrigatório	Recurso
customtkinter	✅ Sim	Interface gráfica moderna
pystray	❌ Opcional	Ícone na bandeja do sistema
Pillow	❌ Opcional	Ícones personalizados
plyer	❌ Opcional	Notificações nativas
psutil	❌ Opcional	Monitoramento condicional (CPU/processos/rede)
keyboard	❌ Opcional	Atalhos globais de teclado
Todos os recursos opcionais degradam graciosamente se as dependências não estiverem instaladas.

🖥️ Uso
Modo gráfico (GUI)
bash
python shutdown_timer.py
# ou
python shutdown_timer.py --gui
Linha de comando (CLI)
bash
# Desligar em 30 minutos
python shutdown_timer.py --shutdown 30

# Suspender em 1 hora
python shutdown_timer.py --suspend 60

# Reiniciar em 15 minutos
python shutdown_timer.py --reboot 15

# Bloquear tela em 5 minutos
python shutdown_timer.py --lock 5

# Cancelar timer ativo
python shutdown_timer.py --cancel

# Verificar status
python shutdown_timer.py --status
Atalhos de teclado (quando habilitados)
Ctrl+Alt+S - Inicia timer com configurações atuais

Ctrl+Alt+X - Cancela timer atual

Ctrl+Alt+W - Alterna visibilidade do widget flutuante

🏗️ Arquitetura
O código segue uma arquitetura modular com separação clara de responsabilidades:

text
ShutdownTimer/
├── SystemController      # Ações de SO (shutdown/suspend/reboot/lock)
├── TimerEngine           # Contagem regressiva thread-safe
├── ConditionMonitor      # Monitoramento condicional (CPU/processo/rede/inatividade)
├── ConfigManager         # Persistência JSON e histórico
├── TrayManager           # Ícone na bandeja do sistema
├── NotificationManager   # Notificações nativas multiplataforma
├── HotkeyManager         # Atalhos globais de teclado
├── ShutdownApp           # Janela principal (UI com CustomTkinter)
├── MiniWidget            # Widget flutuante compacto always-on-top
└── CLI                   # Interface de linha de comando
Características da arquitetura
Thread-safe - Toda comunicação entre threads via root.after()

Fallbacks inteligentes - Recursos opcionais degradam graciosamente

Portável - Suporte a Windows, Linux e macOS

Modular - Componentes fracamente acoplados e reutilizáveis

📁 Arquivos de configuração
~/.shutdown_timer_config.json - Configurações, histórico e estatísticas

~/.shutdown_timer_state.json - Estado do timer ativo (usado pela CLI)

📊 Estatísticas e histórico
O aplicativo mantém um histórico completo de todas as execuções:

Timestamp da ação

Tipo de ação (shutdown/suspend/reboot/lock)

Duração agendada

Status (completa/cancelada)

Estatísticas agregadas:

Total de ações concluídas

Minutos totais agendados

Distribuição por tipo de ação

Energia economizada estimada

🔧 Personalização
Modo Gamer
Configure processos que devem pausar o timer:

Valorant.exe, League of Legends, Blender, etc.

Threshold de inatividade personalizável

Timer Adaptativo
Quando ativo, detecta atividade do usuário nos últimos 2 minutos e estende automaticamente o timer.

Atalhos globais
Personalize as combinações de teclas para iniciar, cancelar e alternar o widget.

📝 Licença
Este projeto está licenciado sob a licença MIT - veja o arquivo LICENSE para detalhes.

🤝 Contribuindo
Contribuições são bem-vindas! Sinta-se à vontade para:

Reportar bugs

Sugerir novas funcionalidades

Enviar pull requests

🙏 Agradecimentos
CustomTkinter - Interface moderna para Tkinter

psutil - Monitoramento do sistema

pystray - Ícone na bandeja

plyer - Notificações nativas

keyboard - Atalhos globais

ShutdownTimer v3.0 - Agendamento inteligente para economizar energia e automatizar seu computador. ⏻
