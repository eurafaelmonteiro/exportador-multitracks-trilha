$ErrorActionPreference = "Stop"

$NomeRepo = "exportador-multitracks-trilha"
$Versao = "v1.0"
$PythonExe = "C:\Users\Rafael\AppData\Local\Python\pythoncore-3.15-64\python.exe"
if (-not (Test-Path $PythonExe)) { $PythonExe = "py" }

$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $InnoCompiler)) { $InnoCompiler = "$env:ProgramFiles\Inno Setup 6\ISCC.exe" }

Write-Host "`n[1/6] Criando arquivos do repositório (.gitignore, requirements.txt, README.md, LICENSE)..." -ForegroundColor Cyan

@"
build/
dist/
Instalador_Pronto/
__pycache__/
*.spec
mapa_campos.json
"@ | Set-Content -Encoding UTF8 ".gitignore"

@"
customtkinter
pillow
numpy
pedalboard
static-ffmpeg
pyinstaller
"@ | Set-Content -Encoding UTF8 "requirements.txt"

@"
MIT License

Copyright (c) 2026 Rafael Monteiro

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"@ | Set-Content -Encoding UTF8 "LICENSE"

@"
# Exportador Multitracks Trilha

Ferramenta gratuita e open source para exportar cenas, repertórios e faixas avulsas do **Trilha Playback** em arquivos de áudio prontos para ensaio, estudo ou split tracks (L/R).

## Funcionalidades
- **Exportação por Cena ou Biblioteca:** Exporta o repertório completo na ordem exata ou músicas selecionadas individualmente.
- **Fidelidade à Mixagem:** Mantém volumes por faixa, mutes, transposição de tom (pitch shift sem alterar bateria/percussão) e ajuste de andamento (BPM).
- **Roteamento Flexível (L/R):** Envie Click/Guia para um lado e Instrumental para o outro, ou tudo em Estéreo.
- **Formatos:** MP3 (192 kbps ou 320 kbps) e WAV sem perda.

## Como Baixar e Usar (Para Músicos)
1. Acesse a aba **[Releases](../../releases)** no menu lateral direito.
2. Baixe o **Instalador** (``Instalador_Exportador_Multitracks_Trilha_$Versao.exe``) ou a **Versão Portátil** (``.exe``).
3. Abra o programa — ele detecta automaticamente a biblioteca do **Trilha Playback** instalada no seu Windows.

> **Aviso do Windows SmartScreen:** Por ser um software independente sem certificado comercial, o Windows pode exibir *"O Windows protegeu o computador"* na primeira abertura. Clique em **Mais informações** > **Executar assim mesmo**.

## Como Rodar pelo Código-Fonte (Para Desenvolvedores)
``````bash
git clone https://github.com/SEU-USUARIO/$NomeRepo.git
cd $NomeRepo
pip install -r requirements.txt
python Exportador_Multitrack.py

"@ | Set-Content -Encoding UTF8 "README.md"

Write-Host "[2/6] Gerando ícone e banners visuais..." -ForegroundColor Cyan
& $PythonExe -c "from PIL import Image, ImageDraw; from Exportador_Multitrack import criar_icone_play; criar_icone_play(256).save('icone.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); lateral = Image.new('RGB', (164, 314), '#111317'); draw = ImageDraw.Draw(lateral); draw.rectangle([0, 0, 5, 314], fill='#E6A83A'); ico = criar_icone_play(96); lateral.paste(ico, (34, 85), ico); lateral.save('banner_lateral.bmp'); topo = Image.new('RGB', (55, 58), '#191C22'); ico_p = criar_icone_play(44); topo.paste(ico_p, (5, 7), ico_p); topo.save('banner_topo.bmp')"

Write-Host "[3/6] Compilando executável portátil com PyInstaller..." -ForegroundColor Cyan
& $PythonExe -m PyInstaller --noconsole --onefile --clean --name "Exportador Multitracks Trilha" --icon="icone.ico" --collect-all customtkinter --collect-all static_ffmpeg --collect-all pedalboard Exportador_Multitrack.py
Copy-Item "dist\Exportador Multitracks Trilha.exe" "dist\Exportador Multitracks Trilha (Portátil).exe" -Force

if (Test-Path $InnoCompiler) {
Write-Host "[4/6] Compilando instalador com Inno Setup..." -ForegroundColor Cyan
& $InnoCompiler "instalador.iss"
} else {
Write-Host "[4/6] Inno Setup não encontrado, pulando geração do instalador..." -ForegroundColor Yellow
}

Write-Host "[5/6] Preparando GitHub CLI e repositório..." -ForegroundColor Cyan
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
winget install --id GitHub.cli -e --source winget --accept-package-agreements --accept-source-agreements
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

$ErrorActionPreference = "Continue"; $ErrorActionPreference = "Continue"; gh auth status 2>$null; $ErrorActionPreference = "Stop"; $ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) {
Write-Host "Autorize o GitHub no navegador que vai abrir..." -ForegroundColor Yellow
gh auth login -p https -h github.com -w
}

$UsuarioGH = (gh api user --jq ".login")
(Get-Content "README.md") -replace "SEU-USUARIO", $UsuarioGH | Set-Content -Encoding UTF8 "README.md"

if (-not (Test-Path ".git")) {
git init
git branch -M main
}

if (-not (git config user.name)) { git config user.name $UsuarioGH }
if (-not (git config user.email)) { git config user.email "$UsuarioGH@users.noreply.github.com" }

git add .
git commit -m "Lançamento $Versao - Exportador Multitracks Trilha"

Write-Host "[6/6] Publicando repositório e Release no GitHub..." -ForegroundColor Cyan
gh repo view "$UsuarioGH/$NomeRepo" 2>$null
if ($LASTEXITCODE -ne 0) {
gh repo create $NomeRepo --public --source=. --remote=origin --push --description "Exportador open source de cenas e multitracks do Trilha Playback com roteamento L/R, tom e BPM."
} else {
git push -u origin main
}

$ArquivosRelease = @("dist\Exportador Multitracks Trilha (Portátil).exe")
$CaminhoInstalador = "Instalador_Pronto\Instalador_Exportador_Multitracks_Trilha_v1.0.exe"
if (Test-Path $CaminhoInstalador) {
$ArquivosRelease += $CaminhoInstalador
}

gh release create $Versao $ArquivosRelease --title "$Versao - Lançamento Oficial" --notes "Baixe abaixo o Instalador para Windows ou a Versão Portátil (execução direta sem instalação)."

Write-Host "`nCONCLUÍDO! Abrindo seu repositório no navegador..." -ForegroundColor Green
Start-Process "https://github.com/$UsuarioGH/$NomeRepo"
