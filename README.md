# Exportador Multitracks Trilha

Ferramenta gratuita e open source para exportar cenas, repertórios e faixas avulsas do **Trilha Playback** em arquivos de áudio prontos para ensaio, estudo ou split tracks (L/R).

## Funcionalidades
- **Exportação por Cena ou Biblioteca:** Exporta o repertório completo na ordem exata ou músicas selecionadas individualmente.
- **Fidelidade à Mixagem:** Mantém volumes por faixa, mutes, transposição de tom (pitch shift sem alterar bateria/percussão) e ajuste de andamento (BPM).
- **Roteamento Flexível (L/R):** Envie Click/Guia para um lado e Instrumental para o outro, ou tudo em Estéreo.
- **Formatos:** MP3 (192 kbps ou 320 kbps) e WAV sem perda.

## Como Baixar e Usar (Para Músicos)
1. Acesse a aba **[Releases](../../releases)** no menu lateral direito.
2. Baixe o **Instalador** (`Instalador_Exportador_Multitracks_Trilha_v1.0.exe`) ou a **Versão Portátil** (`.exe`).
3. Abra o programa — ele detecta automaticamente a biblioteca do **Trilha Playback** instalada no seu Windows.

> **Aviso do Windows SmartScreen:** Por ser um software independente sem certificado comercial, o Windows pode exibir *"O Windows protegeu o computador"* na primeira abertura. Clique em **Mais informações** > **Executar assim mesmo**.

## Como Rodar pelo Código-Fonte (Para Desenvolvedores)
```bash
git clone https://github.com//exportador-multitracks-trilha.git
cd exportador-multitracks-trilha
pip install -r requirements.txt
python Exportador_Multitrack.py

