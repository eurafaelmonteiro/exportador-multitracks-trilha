import os
import re
import sys
import json
import math
import tempfile
import subprocess
import threading
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from pedalboard import Pedalboard, PitchShift
from pedalboard.io import AudioFile
import static_ffmpeg

static_ffmpeg.add_paths()

NOTAS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
EXTENSOES_AUDIO = (".wav", ".mp3", ".ogg", ".flac")

PADRAO_SEM_PITCH = re.compile(
    r"\b(drums?|bateria|kick|bumbo|snare|caixa|hat|hihat|hh|"
    r"cymbals?|pratos?|toms?|surdo|oh|overhead|room|perc|percussao|percussion|"
    r"shaker|tambourine|pandeiro|clap|palmas|sfx|fx|riser|sub\s*drop)\b",
    re.IGNORECASE,
)

OPCOES_ROTEAMENTO = ["Estéreo (L+R)", "Esquerdo (L)", "Direito (R)"]
OPCOES_FORMATO = [
    "MP3 (192 kbps - Leve para WhatsApp)",
    "MP3 (320 kbps - Alta Qualidade)",
    "WAV (Sem perda - Qualidade Máxima)",
]

CONFIG_PADRAO = {
    "pasta_trilha": os.path.join(os.getenv("APPDATA", ""), "Trilha"),
    "versao_esperada_json": 1,
    "campos": {
        "lista_musicas": "musicas",
        "id_musica": "id",
        "pasta_musica": "pasta",
        "titulo_musica": "titulo",
        "tom_musica": "tom",
        "bpm_musica": "bpm",
        "nome_cena": "nome",
        "itens_cena": "itens",
        "id_musica_no_item": "musica",
        "semitons": "semitons",
        "andamento": "andamento",
        "faixas": "faixas",
        "arquivo_faixa": "arquivo",
        "mute_faixa": "mute",
        "volume_faixa": "volumeDb",
    },
}


# ==============================================================================
# 1. GERENCIAMENTO DE CONFIGURAÇÃO E UTILITÁRIOS
# ==============================================================================

class ConfigManager:
    def __init__(self):
        base_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        self.arquivo_config = os.path.join(base_dir, "mapa_campos.json")
        self.dados = self._carregar()

    def _carregar(self) -> dict:
        if not os.path.exists(self.arquivo_config):
            self._salvar(CONFIG_PADRAO)
            return json.loads(json.dumps(CONFIG_PADRAO))
        try:
            with open(self.arquivo_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in CONFIG_PADRAO["campos"].items():
                cfg.setdefault("campos", {}).setdefault(k, v)
            return cfg
        except Exception:
            return json.loads(json.dumps(CONFIG_PADRAO))

    def _salvar(self, conteudo: dict):
        try:
            with open(self.arquivo_config, "w", encoding="utf-8") as f:
                json.dump(conteudo, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    @property
    def pasta_trilha(self) -> str:
        return self.dados.get("pasta_trilha", CONFIG_PADRAO["pasta_trilha"])

    @property
    def versao_esperada(self) -> int:
        return self.dados.get("versao_esperada_json", 1)

    @property
    def campos(self) -> dict:
        return self.dados["campos"]


def calcular_novo_tom(tom_original: str, semitons: int) -> str:
    if not tom_original or semitons == 0:
        return tom_original or ""
    equivalencias = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}
    menor = "m" if tom_original.endswith("m") else ""
    base = tom_original.replace("m", "")
    base_norm = equivalencias.get(base, base)
    if base_norm in NOTAS:
        return NOTAS[(NOTAS.index(base_norm) + semitons) % 12] + menor
    return f"{tom_original} ({semitons:+d}st)"


def formatar_bpm(bpm_base: float | int | None, andamento: float | int | None = 1.0) -> str:
    if not bpm_base or bpm_base <= 0:
        return ""
    fator = andamento if (andamento and andamento > 0) else 1.0
    bpm_real = float(bpm_base) * float(fator)
    if abs(bpm_real - round(bpm_real)) < 0.05:
        return f"{round(bpm_real)}bpm"
    return f"{bpm_real:.1f}bpm"


def montar_sufixo_metadados(tom: str, bpm_str: str) -> str:
    partes = [p for p in (tom, bpm_str) if p]
    return f" ({' - '.join(partes)})" if partes else ""


def faixa_muda_tom(nome_arquivo: str) -> bool:
    nome_limpo = os.path.splitext(nome_arquivo)[0].replace("_", " ").replace("-", " ")
    return not bool(PADRAO_SEM_PITCH.search(nome_limpo))


# ==============================================================================
# 2. LEITURA DOS DADOS DO TRILHA PLAYBACK
# ==============================================================================

@dataclass
class OpcoesExportacao:
    incluir_click: bool
    incluir_guide: bool
    rota_click_guide: str
    rota_instrumental: str
    eh_wav: bool
    bitrate_mp3: str


class TrilhaRepository:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.c = config.campos
        self.musicas: list[dict] = []
        self.musicas_por_id: dict[str, dict] = {}
        self.versoes_por_pasta: dict[str, dict] = {}
        self.cenas: list[dict] = []

    @staticmethod
    def _ler_json(caminho: str) -> dict | None:
        if not os.path.exists(caminho):
            return None
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def recarregar(self) -> list[str]:
        avisos = []
        pasta = self.config.pasta_trilha
        bib = self._ler_json(os.path.join(pasta, "biblioteca.json"))

        if not bib:
            self.musicas, self.musicas_por_id, self.versoes_por_pasta, self.cenas = [], {}, {}, []
            return [f"Não foi possível ler biblioteca.json em: {pasta}"]

        versao_atual = bib.get("versao", 1)
        if versao_atual > self.config.versao_esperada:
            avisos.append(f"Trilha atualizou formato de dados (v{versao_atual}). Modo compatibilidade ativo.")

        self.musicas = bib.get(self.c["lista_musicas"], [])
        self.musicas_por_id = {
            m[self.c["id_musica"]]: m for m in self.musicas if self.c["id_musica"] in m
        }
        self.versoes_por_pasta = self._carregar_versoes(os.path.join(pasta, "versoes"))
        self.cenas = self._carregar_cenas(os.path.join(pasta, "cenas"))
        return avisos

    def _carregar_versoes(self, pasta_versoes: str) -> dict[str, dict]:
        mapa = {}
        if not os.path.exists(pasta_versoes):
            return mapa
        for arq in os.listdir(pasta_versoes):
            if not arq.endswith(".json"):
                continue
            dados = self._ler_json(os.path.join(pasta_versoes, arq))
            if not dados:
                continue
            pasta_norm = os.path.normcase(os.path.normpath(dados.get("pasta", "")))
            principal_id = dados.get("principal")
            lista = dados.get("versoes", [])
            ativa = next((v for v in lista if v.get("id") == principal_id), lista[0] if lista else None)
            if ativa and pasta_norm:
                mapa[pasta_norm] = ativa
        return mapa

    def _carregar_cenas(self, pasta_cenas: str) -> list[dict]:
        if not os.path.exists(pasta_cenas):
            return []
        return [
            dados
            for arq in os.listdir(pasta_cenas)
            if arq.endswith(".json") and (dados := self._ler_json(os.path.join(pasta_cenas, arq)))
        ]


# ==============================================================================
# 3. MOTOR DE PROCESSAMENTO E MIXAGEM DE ÁUDIO (DSP)
# ==============================================================================

class AudioMixEngine:
    def __init__(self, campos: dict):
        self.c = campos

    @staticmethod
    def _aplicar_roteamento(bus: np.ndarray, modo: str) -> np.ndarray:
        if modo == "Estéreo (L+R)":
            return bus
        pico_l = np.max(np.abs(bus[0]))
        pico_r = np.max(np.abs(bus[1]))
        if pico_l < 1e-5:
            mono = bus[1]
        elif pico_r < 1e-5:
            mono = bus[0]
        else:
            mono = 0.5 * (bus[0] + bus[1])

        silencio = np.zeros_like(mono)
        return np.vstack([mono, silencio]) if modo == "Esquerdo (L)" else np.vstack([silencio, mono])

    def _coletar_stems_ativos(self, pasta_audio: str, config_item: dict, opcoes: OpcoesExportacao) -> list[tuple]:
        config_faixas = {
            f[self.c["arquivo_faixa"]]: f
            for f in config_item.get(self.c["faixas"], [])
            if self.c["arquivo_faixa"] in f
        }

        stems = []
        for arq in sorted(os.listdir(pasta_audio)):
            if not arq.lower().endswith(EXTENSOES_AUDIO):
                continue

            nome_lower = arq.lower()
            eh_click = "click" in nome_lower
            eh_guide = "guide" in nome_lower or "guia" in nome_lower

            if (eh_click and not opcoes.incluir_click) or (eh_guide and not opcoes.incluir_guide):
                continue

            cfg = config_faixas.get(arq, {})
            if cfg.get(self.c["mute_faixa"], False):
                continue

            vol_db = cfg.get(self.c["volume_faixa"], 0.0) or 0.0
            ganho = math.pow(10.0, vol_db / 20.0)
            grupo = "cg" if (eh_click or eh_guide) else ("harm" if faixa_muda_tom(arq) else "ritm")
            stems.append((os.path.join(pasta_audio, arq), ganho, grupo))

        return stems

    def processar_musica(
        self,
        prefixo: str,
        musica_info: dict,
        config_item: dict,
        destino: str,
        opcoes: OpcoesExportacao,
        on_status=None,
    ) -> str:
        titulo = musica_info.get(self.c["titulo_musica"], "Musica")
        pasta_audio = musica_info.get(self.c["pasta_musica"], "")

        if not pasta_audio or not os.path.exists(pasta_audio):
            raise FileNotFoundError(f"Pasta de áudio não encontrada: {pasta_audio}")

        stems = self._coletar_stems_ativos(pasta_audio, config_item, opcoes)
        if not stems:
            raise ValueError("Nenhuma faixa ativa para exportar.")

        # 1. Lê cabeçalhos para pré-alocar memória exata
        sr_base = 44100
        max_frames = 0
        for idx, (caminho, _, _) in enumerate(stems):
            with AudioFile(caminho) as af:
                if idx == 0:
                    sr_base = af.samplerate
                frames_estimados = int(math.ceil(af.frames * (sr_base / af.samplerate)))
                max_frames = max(max_frames, frames_estimados)

        buses = {
            "cg": np.zeros((2, max_frames), dtype=np.float32),
            "harm": np.zeros((2, max_frames), dtype=np.float32),
            "ritm": np.zeros((2, max_frames), dtype=np.float32),
        }
        ativos = {"cg": False, "harm": False, "ritm": False}

        # 2. Soma cada faixa diretamente no buffer pré-alocado
        for caminho, ganho, grupo in stems:
            with AudioFile(caminho).resampled_to(sr_base) as af:
                audio = af.read(af.frames).astype(np.float32) * ganho
            if audio.shape[0] == 1:
                audio = np.vstack([audio, audio])
            n = min(audio.shape[1], max_frames)
            buses[grupo][:, :n] += audio[:, :n]
            ativos[grupo] = True

        # 3. Pitch-shift apenas no bus harmônico
        semitons = config_item.get(self.c["semitons"], 0) or 0
        if ativos["harm"] and semitons != 0:
            if on_status:
                on_status(f"   -> Transpondo harmonia ({semitons:+d} st)...")
            board = Pedalboard([PitchShift(semitones=semitons)])
            buses["harm"] = board(buses["harm"], sr_base)

        # 4. Combina instrumental, aplica roteamento L/R e normaliza picos
        mix = np.zeros((2, max_frames), dtype=np.float32)
        if ativos["cg"]:
            mix += self._aplicar_roteamento(buses["cg"], opcoes.rota_click_guide)

        if ativos["harm"] or ativos["ritm"]:
            inst = buses["harm"] + buses["ritm"]
            mix += self._aplicar_roteamento(inst, opcoes.rota_instrumental)

        pico = float(np.max(np.abs(mix)))
        if pico > 0.98:
            mix *= 0.95 / pico

        # 5. Grava arquivo final com Tom e BPM no nome
        andamento = config_item.get(self.c["andamento"], 1.0) or 1.0
        tom_final = calcular_novo_tom(musica_info.get(self.c["tom_musica"], ""), semitons)
        bpm_str = formatar_bpm(musica_info.get(self.c["bpm_musica"]), andamento)
        sufixo = montar_sufixo_metadados(tom_final, bpm_str)

        nome_limpo = re.sub(r'[<>:"/\\|?*]', "", f"{prefixo}{titulo}{sufixo}")
        nome_saida = f"{nome_limpo}.{'wav' if opcoes.eh_wav else 'mp3'}"
        caminho_final = os.path.join(destino, nome_saida)

        tem_andamento = abs(andamento - 1.0) > 0.005

        if opcoes.eh_wav and not tem_andamento:
            with AudioFile(caminho_final, "w", sr_base, 2) as out:
                out.write(mix)
        else:
            self._renderizar_com_ffmpeg(mix, sr_base, caminho_final, opcoes, andamento if tem_andamento else None)

        return nome_saida

    @staticmethod
    def _renderizar_com_ffmpeg(
        mix: np.ndarray,
        sr: int,
        caminho_final: str,
        opcoes: OpcoesExportacao,
        andamento: float | None,
    ):
        fd, temp_wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with AudioFile(temp_wav, "w", sr, 2) as out:
                out.write(mix)

            cmd = ["ffmpeg", "-y", "-i", temp_wav]
            if andamento:
                cmd.extend(["-filter:a", f"atempo={andamento}"])
            if not opcoes.eh_wav:
                cmd.extend(["-b:a", opcoes.bitrate_mp3])
            cmd.append(caminho_final)

            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        finally:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)


# ==============================================================================
# 4. INTERFACE GRÁFICA (TKINTER)
# ==============================================================================

class AppExportador:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Exportador de Áudio - Trilha Playback")
        self.root.geometry("640x660")
        self.root.resizable(False, False)

        self.config = ConfigManager()
        self.repo = TrilhaRepository(self.config)
        self.engine = AudioMixEngine(self.config.campos)

        self.pasta_saida = os.path.join(os.path.expanduser("~"), "Desktop", "Ensaio_Banda")
        self.musicas_filtradas: list[tuple[dict, dict]] = []

        avisos = self.repo.recarregar()
        self._construir_ui()
        for av in avisos:
            self.log(f"[AVISO] {av}")

    def _construir_ui(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill="both", expand=True, pady=(0, 12))

        self._construir_aba_cenas()
        self._construir_aba_biblioteca()
        self._construir_painel_opcoes(frame)

        self.btn_exportar = ttk.Button(frame, text="EXPORTAR ÁUDIOS", command=self._iniciar_exportacao)
        self.btn_exportar.pack(fill="x", ipady=8, pady=(0, 8))

        self.progresso = ttk.Progressbar(frame, mode="determinate")
        self.progresso.pack(fill="x", pady=(0, 8))

        self.txt_log = tk.Text(frame, height=8, font=("Consolas", 9), state="disabled", bg="#f4f4f4")
        self.txt_log.pack(fill="both", expand=True)

    def _construir_aba_cenas(self):
        aba = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(aba, text="  Exportar Cena (Repertório)  ")

        topo = ttk.Frame(aba)
        topo.pack(fill="x")
        ttk.Label(topo, text="Selecione a Cena salva no Trilha:", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(topo, text="Recarregar Dados", command=self._recarregar_dados).pack(side="right")

        self.combo_cenas = ttk.Combobox(aba, state="readonly", font=("Segoe UI", 10))
        self.combo_cenas.pack(fill="x", pady=(6, 10))
        self._atualizar_combo_cenas()

        ttk.Label(
            aba,
            text="Dica: Se você acabou de editar algo no Trilha, clique em 'Recarregar Dados' antes de exportar.",
            foreground="#555",
            wraplength=560,
        ).pack(anchor="w")

    def _construir_aba_biblioteca(self):
        aba = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(aba, text="  Exportar da Biblioteca  ")

        busca_frame = ttk.Frame(aba)
        busca_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(busca_frame, text="Buscar música:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.var_busca = tk.StringVar()
        self.var_busca.trace_add("write", self._filtrar_biblioteca)
        ttk.Entry(busca_frame, textvariable=self.var_busca).pack(side="left", fill="x", expand=True, padx=(8, 0))

        lista_frame = ttk.Frame(aba)
        lista_frame.pack(fill="both", expand=True)

        scroll = ttk.Scrollbar(lista_frame)
        scroll.pack(side="right", fill="y")

        self.lista_musicas = tk.Listbox(
            lista_frame, selectmode="extended", font=("Segoe UI", 9), height=6, yscrollcommand=scroll.set
        )
        self.lista_musicas.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.lista_musicas.yview)

        ttk.Label(
            aba,
            text="Dica: Segure Ctrl ou Shift para selecionar várias músicas de uma vez.",
            foreground="#555",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(4, 0))

        self._filtrar_biblioteca()

    def _construir_painel_opcoes(self, parent: ttk.Frame):
        box = ttk.LabelFrame(parent, text="Roteamento (L/R), Formato e Saída", padding=10)
        box.pack(fill="x", pady=(0, 10))

        # Linha 1
        l1 = ttk.Frame(box)
        l1.pack(fill="x", pady=(0, 8))
        self.var_click = tk.BooleanVar(value=True)
        self.var_guide = tk.BooleanVar(value=True)
        ttk.Checkbutton(l1, text="Incluir Click", variable=self.var_click).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(l1, text="Incluir Guide", variable=self.var_guide).pack(side="left", padx=(0, 18))
        ttk.Label(l1, text="Saída Click/Guia:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.combo_rota_cg = ttk.Combobox(l1, values=OPCOES_ROTEAMENTO, state="readonly", width=15)
        self.combo_rota_cg.current(0)
        self.combo_rota_cg.pack(side="left", padx=(6, 0))

        # Linha 2
        l2 = ttk.Frame(box)
        l2.pack(fill="x", pady=(0, 8))
        ttk.Label(l2, text="Saída Instrumental:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.combo_rota_inst = ttk.Combobox(l2, values=OPCOES_ROTEAMENTO, state="readonly", width=15)
        self.combo_rota_inst.current(0)
        self.combo_rota_inst.pack(side="left", padx=(6, 18))
        ttk.Label(l2, text="Formato:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.combo_formato = ttk.Combobox(l2, values=OPCOES_FORMATO, state="readonly", width=31)
        self.combo_formato.current(0)
        self.combo_formato.pack(side="left", padx=(6, 0))

        # Linha 3
        l3 = ttk.Frame(box)
        l3.pack(fill="x")
        ttk.Label(l3, text="Salvar em:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.lbl_pasta = ttk.Label(l3, text=self.pasta_saida, foreground="#444")
        self.lbl_pasta.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(l3, text="Alterar...", command=self._escolher_pasta).pack(side="right")

    def _atualizar_combo_cenas(self):
        chave_nome = self.config.campos["nome_cena"]
        nomes = [c.get(chave_nome, "Sem nome") for c in self.repo.cenas]
        self.combo_cenas["values"] = nomes
        if nomes:
            self.combo_cenas.current(0)

    def _recarregar_dados(self):
        avisos = self.repo.recarregar()
        self._atualizar_combo_cenas()
        self._filtrar_biblioteca()
        self.log("Dados do Trilha recarregados.")
        for av in avisos:
            self.log(f"[AVISO] {av}")

    def _filtrar_biblioteca(self, *_):
        c = self.config.campos
        termo = self.var_busca.get().lower().strip()
        self.lista_musicas.delete(0, "end")
        self.musicas_filtradas.clear()

        for m in sorted(self.repo.musicas, key=lambda x: x.get(c["titulo_musica"], "").lower()):
            titulo = m.get(c["titulo_musica"], "Sem título")
            if termo and termo not in titulo.lower():
                continue

            pasta_norm = os.path.normcase(os.path.normpath(m.get(c["pasta_musica"], "")))
            versao = self.repo.versoes_por_pasta.get(pasta_norm, {})
            semitons = versao.get(c["semitons"], 0) or 0
            andamento = versao.get(c["andamento"], 1.0) or 1.0

            tom = calcular_novo_tom(m.get(c["tom_musica"], ""), semitons)
            bpm_str = formatar_bpm(m.get(c["bpm_musica"]), andamento)

            detalhes_tom = f"{tom}{f' ({semitons:+d}st)' if semitons != 0 else ''}"
            etiqueta = " | ".join(p for p in (detalhes_tom, bpm_str) if p)
            tag = f" [{etiqueta}]" if etiqueta else ""

            self.musicas_filtradas.append((m, versao))
            self.lista_musicas.insert("end", f"{titulo}{tag}")

    def log(self, msg: str):
        def _append():
            self.txt_log.config(state="normal")
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")

        self.root.after(0, _append)

    def _set_progresso(self, valor: int, maximo: int | None = None):
        def _update():
            if maximo is not None:
                self.progresso["maximum"] = maximo
            self.progresso["value"] = valor

        self.root.after(0, _update)

    def _escolher_pasta(self):
        if pasta := filedialog.askdirectory():
            self.pasta_saida = pasta
            self.lbl_pasta.config(text=pasta)

    def _montar_fila(self) -> tuple[str, list[tuple[str, dict, dict]]] | None:
        c = self.config.campos
        if self.notebook.index(self.notebook.select()) == 0:
            if not self.repo.cenas:
                messagebox.showwarning("Aviso", "Nenhuma cena encontrada.")
                return None
            cena = self.repo.cenas[self.combo_cenas.current()]
            subpasta = re.sub(r'[<>:"/\\|?*]', "-", cena.get(c["nome_cena"], "Repertorio"))
            fila = [
                (f"{i:02d} - ", m_info, item)
                for i, item in enumerate(cena.get(c["itens_cena"], []), start=1)
                if (m_info := self.repo.musicas_por_id.get(item.get(c["id_musica_no_item"])))
            ]
            return subpasta, fila

        selecionados = self.lista_musicas.curselection()
        if not selecionados:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma música na Biblioteca.")
            return None
        return "Biblioteca_Avulsas", [("", *self.musicas_filtradas[idx]) for idx in selecionados]

    def _iniciar_exportacao(self):
        resultado = self._montar_fila()
        if not resultado:
            return
        subpasta, fila = resultado
        if not fila:
            messagebox.showwarning("Aviso", "Nenhuma música válida para exportar.")
            return

        fmt = self.combo_formato.get()
        opcoes = OpcoesExportacao(
            incluir_click=self.var_click.get(),
            incluir_guide=self.var_guide.get(),
            rota_click_guide=self.combo_rota_cg.get(),
            rota_instrumental=self.combo_rota_inst.get(),
            eh_wav=fmt.startswith("WAV"),
            bitrate_mp3="320k" if "320" in fmt else "192k",
        )

        self.btn_exportar.config(state="disabled")
        threading.Thread(target=self._executar_fila, args=(subpasta, fila, opcoes), daemon=True).start()

    def _executar_fila(self, subpasta: str, fila: list, opcoes: OpcoesExportacao):
        c = self.config.campos
        destino = os.path.join(self.pasta_saida, subpasta)
        os.makedirs(destino, exist_ok=True)

        self._set_progresso(0, len(fila))
        self.log(f"\nExportando {len(fila)} música(s) | {'WAV' if opcoes.eh_wav else 'MP3 ' + opcoes.bitrate_mp3}")

        sucessos = 0
        for i, (prefixo, musica_info, config_item) in enumerate(fila, start=1):
            titulo = musica_info.get(c["titulo_musica"], f"Musica_{i}")
            semitons = config_item.get(c["semitons"], 0) or 0
            andamento = config_item.get(c["andamento"], 1.0) or 1.0
            tom = calcular_novo_tom(musica_info.get(c["tom_musica"], ""), semitons)
            bpm_str = formatar_bpm(musica_info.get(c["bpm_musica"]), andamento)

            info_log = ", ".join(p for p in (f"Tom: {tom}" if tom else "", f"{semitons:+d} st", bpm_str) if p)
            self.log(f"[{i}/{len(fila)}] {titulo} ({info_log})...")

            try:
                arquivo_gerado = self.engine.processar_musica(
                    prefixo, musica_info, config_item, destino, opcoes, on_status=self.log
                )
                sucessos += 1
                self.log(f"   -> OK: {arquivo_gerado}")
            except Exception as erro:
                self.log(f"   -> FALHA em '{titulo}': {erro}")

            self._set_progresso(i)

        self.log(f"\nCONCLUÍDO! {sucessos}/{len(fila)} música(s) exportada(s).")
        self.root.after(0, lambda: self._finalizar_ui(sucessos, len(fila), destino))

    def _finalizar_ui(self, sucessos: int, total: int, destino: str):
        self.btn_exportar.config(state="normal")
        if sucessos > 0:
            messagebox.showinfo("Sucesso!", f"{sucessos} de {total} música(s) exportada(s) em:\n{destino}")
            os.startfile(destino)


if __name__ == "__main__":
    root = tk.Tk()
    AppExportador(root)
    root.mainloop()