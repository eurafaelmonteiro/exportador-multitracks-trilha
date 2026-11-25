#define MyAppName "Exportador Multitracks Trilha"
#define MyAppVersion "1.0"
#define MyAppPublisher "Rafael Monteiro"
#define MyAppExeName "Exportador Multitracks Trilha.exe"

[Setup]
AppId={{8E4F2A19-7B3C-4D9E-A152-6C9F0B3D4E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=Instalador_Pronto
OutputBaseFilename=Instalador_Exportador_Multitracks_Trilha_v1.0
SetupIconFile=icone.ico
WizardImageFile=banner_lateral.bmp
WizardSmallImageFile=banner_topo.bmp
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Messages]
portuguese.WelcomeLabel1=Bem-vindo ao {#MyAppName}
portuguese.WelcomeLabel2=Este assistente instalará o {#MyAppName} v{#MyAppVersion} no seu computador.%n%nExporte suas cenas e multitracks do Trilha Playback com roteamento L/R, transposição de tom e ajuste de andamento em segundos.%n%nClique em Avançar para continuar.
portuguese.FinishedHeadingLabel=Instalação Concluída!
portuguese.FinishedLabel=O {#MyAppName} foi instalado com sucesso e já está pronto para uso.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
