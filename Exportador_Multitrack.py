import os
import re
import sys
import json
import math
import tempfile
import threading
import subprocess
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw
import numpy as np
from pedalboard import Pedalboard, PitchShift
from pedalboard.io import AudioFile
import static_ffmpeg

static_ffmpeg.add_paths()

# ==============================================================================
# 1. CONSTANTES, PALETA DE CORES E CONFIGURAÇÕES
# ==============================================================================

TEMA = {
    "bg_principal": "#111317",
    "bg_card": "#191C22",
    "bg_input": "#21252E",
    "bg_hover": "#2A2F3A",
    "borda": "#2A2F3B",
    "ambar": "#E6A83A",
    "ambar_claro": "#F7C868",
    "ambar_hover": "#F2B649",
    "texto_on_ambar": "#111317",
    "texto_principal": "#F2F4F8",
    "texto_secundario": "#8A92A0",
    "raio_card": 12,
    "raio_botao": 8,
    "largura_maxima_conteudo": 820,
}

NOTAS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
EXTENSOES_AUDIO = (".wav", ".mp3", ".ogg", ".flac")

PADRAO_SEM_PITCH = re.compile(
    r"\b(drums?|bateria|kick|bumbo|snare|caixa|hat|hihat|hh|"
    r"cymbals?|pratos?|toms?|surdo|oh|overhead|room|perc|percussao|percussion|"
    r"shaker|tambourine|pandeiro|clap|palmas|sfx|fx|riser|sub\s*drop)\b",
    re.IGNORECASE,
)

OPCOES_ROTEAMENTO = ["Estéreo", "Esquerdo (L)", "Direito (R)"]
OPCOES_FORMATO = [
    "MP3 192 kbps (Leve / WhatsApp)",
    "MP3 320 kbps (Alta Qualidade)",
    "WAV (Sem perda / Estúdio)",
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
# 2. GERADOR DE ÍCONE EXCLUSIVO (PLAY ESTILIZADO)
# ==============================================================================

def criar_icone_play(tamanho: int = 128) -> Image.Image:
    """Desenha um ícone Play geométrico em camadas (inspirado no Trilha, sem ser igual)."""
    img = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margem = int(tamanho * 0.04)
    raio = int(tamanho * 0.24)
    borda = max(2, int(tamanho * 0.045))

    draw.rounded_rectangle(
        [margem, margem, tamanho - margem, tamanho - margem],
        radius=raio,
        fill="#191C22",
        outline="#E6A83A",
        width=borda,
    )

    tri_sombra = [
        (int(tamanho * 0.34), int(tamanho * 0.27)),
        (int(tamanho * 0.34), int(tamanho * 0.73)),
        (int(tamanho * 0.73), int(tamanho * 0.50)),
    ]
    draw.polygon(tri_sombra, fill="#8C621C")

    tri_principal = [
        (int(tamanho * 0.39), int(tamanho * 0.30)),
        (int(tamanho * 0.39), int(tamanho * 0.70)),
        (int(tamanho * 0.75), int(tamanho * 0.50)),
    ]
    draw.polygon(tri_principal, fill="#E6A83A")

    tri_brilho = [
        (int(tamanho * 0.39), int(tamanho * 0.30)),
        (int(tamanho * 0.39), int(tamanho * 0.50)),
        (int(tamanho * 0.75), int(tamanho * 0.50)),
    ]
    draw.polygon(tri_brilho, fill="#F7C868")

    return img


# ==============================================================================
# 3. GERENCIAMENTO DE CONFIGURAÇÃO E UTILITÁRIOS MUSICAIS
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
# 4. REPOSITÓRIO DE DADOS DO TRILHA PLAYBACK
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

        musicas_brutas = bib.get(self.c["lista_musicas"], [])
        self.musicas = sorted(musicas_brutas, key=lambda x: x.get(self.c["titulo_musica"], "").lower())
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
        cenas_lidas = [
            dados
            for arq in os.listdir(pasta_cenas)
            if arq.endswith(".json") and (dados := self._ler_json(os.path.join(pasta_cenas, arq)))
        ]
        return sorted(cenas_lidas, key=lambda x: x.get(self.c["nome_cena"], "").lower())


# ==============================================================================
# 5. MOTOR DE ÁUDIO DE ALTA PERFORMANCE (IN-MEMORY + PARALLEL + PIPE)
# ==============================================================================

class AudioMixEngine:
    def __init__(self, campos: dict):
        self.c = campos

    @staticmethod
    def _aplicar_roteamento(bus: np.ndarray, modo: str) -> np.ndarray:
        if modo == "Estéreo":
            return bus
        pico_l = float(np.max(np.abs(bus[0])))
        pico_r = float(np.max(np.abs(bus[1])))
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

    @staticmethod
    def _carregar_stem_em_memoria(item_stem: tuple[str, float, str], sr_base: int) -> tuple[np.ndarray, str]:
        caminho, ganho, grupo = item_stem
        with AudioFile(caminho).resampled_to(sr_base) as af:
            audio = af.read(af.frames).astype(np.float32) * ganho
        if audio.shape[0] == 1:
            audio = np.vstack([audio, audio])
        return audio, grupo

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

        with AudioFile(stems[0][0]) as af0:
            sr_base = af0.samplerate

        # Carrega e reamostra todas as faixas simultaneamente na memória RAM
        workers_io = min(len(stems), max(4, os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=workers_io) as pool:
            stems_carregados = list(
                pool.map(lambda s: self._carregar_stem_em_memoria(s, sr_base), stems)
            )

        max_frames = max(audio.shape[1] for audio, _ in stems_carregados)

        buses = {
            "cg": np.zeros((2, max_frames), dtype=np.float32),
            "harm": np.zeros((2, max_frames), dtype=np.float32),
            "ritm": np.zeros((2, max_frames), dtype=np.float32),
        }
        ativos = {"cg": False, "harm": False, "ritm": False}

        for audio, grupo in stems_carregados:
            n = audio.shape[1]
            buses[grupo][:, :n] += audio
            ativos[grupo] = True

        del stems_carregados  # Libera buffers individuais imediatamente

        semitons = config_item.get(self.c["semitons"], 0) or 0
        if ativos["harm"] and semitons != 0:
            if on_status:
                on_status(f"   -> [{titulo}] Transpondo harmonia ({semitons:+d} st)...")
            board = Pedalboard([PitchShift(semitones=semitons)])
            buses["harm"] = board(buses["harm"], sr_base)

        mix = np.zeros((2, max_frames), dtype=np.float32)
        if ativos["cg"]:
            mix += self._aplicar_roteamento(buses["cg"], opcoes.rota_click_guide)

        if ativos["harm"] or ativos["ritm"]:
            inst = buses["harm"] + buses["ritm"]
            mix += self._aplicar_roteamento(inst, opcoes.rota_instrumental)

        pico = float(np.max(np.abs(mix)))
        if pico > 0.98:
            mix *= 0.95 / pico

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
            self._renderizar_direto_ffmpeg(
                mix, sr_base, caminho_final, opcoes, andamento if tem_andamento else None
            )

        return nome_saida

    @staticmethod
    def _renderizar_direto_ffmpeg(
        mix: np.ndarray,
        sr: int,
        caminho_final: str,
        opcoes: OpcoesExportacao,
        andamento: float | None,
    ):
        """Envia o áudio float32 direto da RAM para o stdin do FFmpeg sem criar arquivos temporários."""
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "f32le",
            "-ar", str(sr),
            "-ac", "2",
            "-i", "pipe:0",
        ]
        if andamento:
            cmd.extend(["-filter:a", f"atempo={andamento}"])
        if not opcoes.eh_wav:
            cmd.extend(["-b:a", opcoes.bitrate_mp3])
        cmd.append(caminho_final)

        pcm_bytes = np.ascontiguousarray(mix.T, dtype=np.float32).tobytes()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        proc.communicate(input=pcm_bytes)


# ==============================================================================
# 6. COMPONENTES VISUAIS CUSTOMIZADOS (SCROLL TRACKPAD + BARRA TRANSPARENTE)
# ==============================================================================

class ListaRolavelFluida(ctk.CTkScrollableFrame):
    """ScrollableFrame otimizado para Trackpad (gesto 2 dedos) e Mouse sem travar em itens internos."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._scroll_acumulado = 0.0

        # Remove os binds padrão de Enter/Leave que quebram o scroll ao passar sobre checkboxes
        self._parent_canvas.unbind("<Enter>")
        self._parent_canvas.unbind("<Leave>")
        self._parent_canvas.configure(yscrollincrement=18)

    def processar_scroll(self, delta: int):
        if not delta:
            return
        if (self._scroll_acumulado > 0 and delta < 0) or (self._scroll_acumulado < 0 and delta > 0):
            self._scroll_acumulado = 0.0

        self._scroll_acumulado += delta
        sensibilidade = 28.0  # Resposta suave e imediata para trackpad e mouse

        if abs(self._scroll_acumulado) >= sensibilidade:
            passos = int(-self._scroll_acumulado / sensibilidade)
            self._scroll_acumulado += passos * sensibilidade
            self._parent_canvas.yview_scroll(passos, "units")


class BarraProgressoTexto(tk.Canvas):
    """Barra de progresso espessa desenhada em Canvas com texto sem fundo preto."""

    def __init__(self, master, altura: int = 28, **kwargs):
        super().__init__(
            master,
            height=altura,
            bg=TEMA["bg_principal"],
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self._valor = 0.0
        self._texto = "Pronto para exportar (0%)"
        self.bind("<Configure>", lambda _: self._desenhar())

    def definir(self, fracao: float, texto: str):
        self._valor = max(0.0, min(1.0, fracao))
        self._texto = texto
        self._desenhar()

    def _desenhar(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return

        r = 8
        # Trilho de fundo
        self._criar_retangulo_arredondado(
            1, 1, w - 1, h - 1, r, fill=TEMA["bg_card"], outline=TEMA["borda"], width=1
        )

        largura_preenchida = int((w - 2) * self._valor)
        if largura_preenchida > 4:
            self._criar_retangulo_arredondado(
                1, 1, largura_preenchida + 1, h - 1, r, fill=TEMA["ambar"], outline=""
            )

        fonte = ("Segoe UI", 10, "bold")
        # Texto claro sobre a área ainda vazia
        self.create_text(
            w / 2, h / 2, text=self._texto, fill=TEMA["texto_principal"], font=fonte
        )

        # Texto escuro sobre a parte preenchida em âmbar (contraste perfeito sem caixa de fundo)
        if largura_preenchida > 20:
            item_escuro = self.create_text(
                w / 2, h / 2, text=self._texto, fill=TEMA["texto_on_ambar"], font=fonte
            )
            # Recorta visualmente o texto escuro apenas até a borda da barra âmbar
            if largura_preenchida < w - 2:
                self._criar_retangulo_arredondado(
                    largura_preenchida + 1, 2, w - 2, h - 2, r, fill=TEMA["bg_card"], outline=""
                )
                self.create_text(
                    w / 2, h / 2, text=self._texto, fill=TEMA["texto_principal"], font=fonte
                )
                self.tag_raise(item_escuro)
                # Redesenha a faixa vazia à direita para manter o corte limpo
                self.create_rectangle(
                    largura_preenchida + 1, 2, w - r, h - 2, fill=TEMA["bg_card"], outline=""
                )
                self._criar_retangulo_arredondado(
                    max(largura_preenchida + 1, w - r * 2),
                    2,
                    w - 2,
                    h - 2,
                    r,
                    fill=TEMA["bg_card"],
                    outline="",
                )
                # Texto claro apenas na metade direita não preenchida
                bbox = self.bbox(item_escuro)
                if bbox and largura_preenchida < bbox[2]:
                    # Usa texto claro com contorno sutil na transição
                    self.delete(item_escuro)
                    cor_texto = (
                        TEMA["texto_on_ambar"] if largura_preenchida > (w * 0.52) else TEMA["texto_principal"]
                    )
                    self.create_text(w / 2, h / 2, text=self._texto, fill=cor_texto, font=fonte)

    def _criar_retangulo_arredondado(self, x1, y1, x2, y2, r, **kwargs):
        r = min(r, abs(x2 - x1) // 2, abs(y2 - y1) // 2)
        pontos = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(pontos, smooth=True, **kwargs)


# ==============================================================================
# 7. APLICAÇÃO PRINCIPAL (INTERFACE GRÁFICA RESPONSIVA)
# ==============================================================================

ctk.set_appearance_mode("dark")


class AppExportador(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Exportador Multitracks Trilha")
        self.geometry("760x760")
        self.minsize(640, 680)
        self.configure(fg_color=TEMA["bg_principal"])

        self._configurar_icone_janela()

        self.config = ConfigManager()
        self.repo = TrilhaRepository(self.config)
        self.engine = AudioMixEngine(self.config.campos)

        self.pasta_saida = os.path.join(os.path.expanduser("~"), "Desktop", "Ensaio_Banda")
        self.modo_atual = "Cena (Repertório)"
        self.cena_selecionada_idx = tk.IntVar(value=0)
        self.selecionados_bib: dict[str, ctk.BooleanVar] = {}

        # Cache de widgets das listas para filtragem instantânea em RAM
        self._itens_ui_cenas: list[tuple[str, ctk.CTkFrame]] = []
        self._itens_ui_bib: list[tuple[str, ctk.CTkFrame]] = []
        self._ultima_margem_lateral = -1

        avisos = self.repo.recarregar()
        self._construir_ui()

        self.bind("<Configure>", self._ao_redimensionar_janela)
        self.bind_all("<MouseWheel>", self._ao_rolar_mouse_global, add="+")

        for av in avisos:
            self.log(f"[AVISO] {av}")

    def _configurar_icone_janela(self):
        try:
            img_logo = criar_icone_play(128)
            self.logo_header_img = ctk.CTkImage(light_image=img_logo, dark_image=img_logo, size=(38, 38))

            fd, self._caminho_ico_temp = tempfile.mkstemp(suffix=".ico")
            os.close(fd)
            img_logo.save(self._caminho_ico_temp, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            self.iconbitmap(self._caminho_ico_temp)
        except Exception:
            self.logo_header_img = None

    def _ao_redimensionar_janela(self, event):
        if event.widget is not self or event.width < 100:
            return
        max_px = int(TEMA["largura_maxima_conteudo"] * self._get_window_scaling())
        margem = max(0, (event.width - max_px) // 2)
        if margem != self._ultima_margem_lateral:
            self._ultima_margem_lateral = margem
            self.grid_columnconfigure(0, minsize=margem)
            self.grid_columnconfigure(2, minsize=margem)

    def _ao_rolar_mouse_global(self, event):
        lista_ativa = self.scroll_cenas if self.modo_atual == "Cena (Repertório)" else self.scroll_bib
        if not lista_ativa.winfo_ismapped():
            return
        try:
            px, py = self.winfo_pointerxy()
            sx = lista_ativa.winfo_rootx()
            sy = lista_ativa.winfo_rooty()
            sw = lista_ativa.winfo_width()
            sh = lista_ativa.winfo_height()

            if sx <= px <= (sx + sw) and sy <= py <= (sy + sh):
                lista_ativa.processar_scroll(event.delta)
                return "break"
        except Exception:
            pass

    def _construir_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=0)

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew", padx=20, pady=18)

        self._construir_cabecalho(self.container)
        self._construir_seletor_origem(self.container)
        self._construir_painel_roteamento(self.container)
        self._construir_rodape_acao(self.container)

    # --- CABEÇALHO ---
    def _construir_cabecalho(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        esq = ctk.CTkFrame(header, fg_color="transparent")
        esq.pack(side="left")

        if self.logo_header_img:
            ctk.CTkLabel(esq, text="", image=self.logo_header_img).pack(side="left", padx=(0, 12))

        titulos = ctk.CTkFrame(esq, fg_color="transparent")
        titulos.pack(side="left")
        ctk.CTkLabel(
            titulos,
            text="EXPORTADOR MULTITRACKS",
            font=("Segoe UI", 16, "bold"),
            text_color=TEMA["texto_principal"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            titulos,
            text="TRILHA PLAYBACK • ENSAIO E SPLIT TRACKS",
            font=("Segoe UI", 10, "bold"),
            text_color=TEMA["texto_secundario"],
        ).pack(anchor="w")

        btn_reload = ctk.CTkButton(
            header,
            text="↻ Sincronizar Trilha",
            width=145,
            height=34,
            corner_radius=TEMA["raio_botao"],
            fg_color=TEMA["bg_card"],
            hover_color=TEMA["bg_hover"],
            border_width=1,
            border_color=TEMA["borda"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 12),
            command=self._recarregar_dados,
        )
        btn_reload.pack(side="right")

    # --- CARD 1: SELEÇÃO DE CENA OU BIBLIOTECA (PADRONIZADOS) ---
    def _construir_seletor_origem(self, parent):
        card = ctk.CTkFrame(
            parent,
            fg_color=TEMA["bg_card"],
            corner_radius=TEMA["raio_card"],
            border_width=1,
            border_color=TEMA["borda"],
        )
        card.pack(fill="both", expand=True, pady=(0, 12))

        topo = ctk.CTkFrame(card, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=(14, 10))

        ctk.CTkLabel(
            topo,
            text="ORIGEM DO REPERTÓRIO",
            font=("Segoe UI", 11, "bold"),
            text_color=TEMA["texto_secundario"],
        ).pack(side="left")

        self.seg_modo = ctk.CTkSegmentedButton(
            topo,
            values=["Cena (Repertório)", "Biblioteca"],
            selected_color=TEMA["ambar"],
            selected_hover_color=TEMA["ambar_hover"],
            unselected_color=TEMA["bg_input"],
            unselected_hover_color=TEMA["bg_hover"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 12, "bold"),
            command=self._trocar_aba,
        )
        self.seg_modo.set("Cena (Repertório)")
        self.seg_modo.pack(side="right")

        self.area_conteudo = ctk.CTkFrame(card, fg_color="transparent")
        self.area_conteudo.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # --- ABA 1: CENAS (PADRONIZADA COM BUSCA + LISTA ROLÁVEL) ---
        self.view_cenas = ctk.CTkFrame(self.area_conteudo, fg_color="transparent")
        self.entry_busca_cenas = ctk.CTkEntry(
            self.view_cenas,
            placeholder_text="🔍  Filtrar cenas do repertório...",
            height=34,
            corner_radius=TEMA["raio_botao"],
            fg_color=TEMA["bg_input"],
            border_color=TEMA["borda"],
            text_color=TEMA["texto_principal"],
        )
        self.entry_busca_cenas.pack(fill="x", pady=(0, 8))
        self.entry_busca_cenas.bind("<KeyRelease>", lambda _: self._filtrar_lista_cenas())

        self.scroll_cenas = ListaRolavelFluida(
            self.view_cenas,
            height=135,
            fg_color=TEMA["bg_input"],
            corner_radius=TEMA["raio_botao"],
        )
        self.scroll_cenas.pack(fill="both", expand=True)
        self._construir_itens_cenas()

        # --- ABA 2: BIBLIOTECA ---
        self.view_bib = ctk.CTkFrame(self.area_conteudo, fg_color="transparent")
        self.entry_busca_bib = ctk.CTkEntry(
            self.view_bib,
            placeholder_text="🔍  Filtrar músicas da biblioteca...",
            height=34,
            corner_radius=TEMA["raio_botao"],
            fg_color=TEMA["bg_input"],
            border_color=TEMA["borda"],
            text_color=TEMA["texto_principal"],
        )
        self.entry_busca_bib.pack(fill="x", pady=(0, 8))
        self.entry_busca_bib.bind("<KeyRelease>", lambda _: self._filtrar_lista_biblioteca())

        self.scroll_bib = ListaRolavelFluida(
            self.view_bib,
            height=135,
            fg_color=TEMA["bg_input"],
            corner_radius=TEMA["raio_botao"],
        )
        self.scroll_bib.pack(fill="both", expand=True)
        self._construir_itens_biblioteca()

        self.view_cenas.pack(fill="both", expand=True)

    # --- CARD 2: ROTEAMENTO L/R E FORMATO ---
    def _construir_painel_roteamento(self, parent):
        card = ctk.CTkFrame(
            parent,
            fg_color=TEMA["bg_card"],
            corner_radius=TEMA["raio_card"],
            border_width=1,
            border_color=TEMA["borda"],
        )
        card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            card,
            text="MIXAGEM, ROTEAMENTO (L / R) E FORMATO",
            font=("Segoe UI", 11, "bold"),
            text_color=TEMA["texto_secundario"],
        ).pack(anchor="w", padx=16, pady=(12, 10))

        l_switches = ctk.CTkFrame(card, fg_color="transparent")
        l_switches.pack(fill="x", padx=16, pady=(0, 10))

        self.var_click = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            l_switches,
            text="Incluir Click (Metrônomo)",
            variable=self.var_click,
            progress_color=TEMA["ambar"],
            button_color=TEMA["texto_principal"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 12),
        ).pack(side="left", padx=(0, 24))

        self.var_guide = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            l_switches,
            text="Incluir Guide (Guia de Voz)",
            variable=self.var_guide,
            progress_color=TEMA["ambar"],
            button_color=TEMA["texto_principal"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 12),
        ).pack(side="left")

        l_rotas = ctk.CTkFrame(card, fg_color="transparent")
        l_rotas.pack(fill="x", padx=16, pady=(0, 10))

        col_cg = ctk.CTkFrame(l_rotas, fg_color="transparent")
        col_cg.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkLabel(
            col_cg, text="Saída Click / Guia:", font=("Segoe UI", 11, "bold"), text_color=TEMA["texto_secundario"]
        ).pack(anchor="w", pady=(0, 4))
        self.seg_rota_cg = ctk.CTkSegmentedButton(
            col_cg,
            values=OPCOES_ROTEAMENTO,
            selected_color=TEMA["ambar"],
            selected_hover_color=TEMA["ambar_hover"],
            unselected_color=TEMA["bg_input"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 11, "bold"),
        )
        self.seg_rota_cg.set("Estéreo")
        self.seg_rota_cg.pack(fill="x")

        col_inst = ctk.CTkFrame(l_rotas, fg_color="transparent")
        col_inst.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkLabel(
            col_inst, text="Saída Instrumental:", font=("Segoe UI", 11, "bold"), text_color=TEMA["texto_secundario"]
        ).pack(anchor="w", pady=(0, 4))
        self.seg_rota_inst = ctk.CTkSegmentedButton(
            col_inst,
            values=OPCOES_ROTEAMENTO,
            selected_color=TEMA["ambar"],
            selected_hover_color=TEMA["ambar_hover"],
            unselected_color=TEMA["bg_input"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 11, "bold"),
        )
        self.seg_rota_inst.set("Estéreo")
        self.seg_rota_inst.pack(fill="x")

        l_saida = ctk.CTkFrame(card, fg_color="transparent")
        l_saida.pack(fill="x", padx=16, pady=(2, 14))

        self.combo_formato = ctk.CTkComboBox(
            l_saida,
            values=OPCOES_FORMATO,
            state="readonly",
            width=245,
            height=34,
            corner_radius=TEMA["raio_botao"],
            fg_color=TEMA["bg_input"],
            border_color=TEMA["borda"],
            button_color=TEMA["bg_hover"],
            dropdown_fg_color=TEMA["bg_card"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 12),
        )
        self.combo_formato.set(OPCOES_FORMATO[0])
        self.combo_formato.pack(side="left", padx=(0, 10))

        self.btn_pasta = ctk.CTkButton(
            l_saida,
            text=f"📁  {os.path.basename(self.pasta_saida)}",
            height=34,
            corner_radius=TEMA["raio_botao"],
            fg_color=TEMA["bg_input"],
            hover_color=TEMA["bg_hover"],
            border_width=1,
            border_color=TEMA["borda"],
            text_color=TEMA["texto_principal"],
            font=("Segoe UI", 12),
            command=self._escolher_pasta,
        )
        self.btn_pasta.pack(side="left", fill="x", expand=True)

    # --- RODAPÉ: BOTÃO, BARRA DE PROGRESSO LIMPA E CONSOLE ---
    def _construir_rodape_acao(self, parent):
        self.btn_exportar = ctk.CTkButton(
            parent,
            text="EXPORTAR ÁUDIOS",
            height=44,
            corner_radius=TEMA["raio_botao"],
            fg_color=TEMA["ambar"],
            hover_color=TEMA["ambar_hover"],
            text_color=TEMA["texto_on_ambar"],
            font=("Segoe UI", 14, "bold"),
            command=self._iniciar_exportacao,
        )
        self.btn_exportar.pack(fill="x", pady=(0, 10))

        self.barra_progresso = BarraProgressoTexto(parent, altura=28)
        self.barra_progresso.pack(fill="x", pady=(0, 10))

        self.txt_log = ctk.CTkTextbox(
            parent,
            height=115,
            corner_radius=TEMA["raio_card"],
            fg_color=TEMA["bg_card"],
            border_width=1,
            border_color=TEMA["borda"],
            text_color=TEMA["texto_secundario"],
            font=("Consolas", 11),
            state="disabled",
        )
        self.txt_log.pack(fill="both", expand=True)

    # --- GERENCIAMENTO DAS LISTAS (CENAS E BIBLIOTECA EM CACHE) ---
    def _trocar_aba(self, valor: str):
        self.modo_atual = valor
        if valor == "Cena (Repertório)":
            self.view_bib.pack_forget()
            self.view_cenas.pack(fill="both", expand=True)
        else:
            self.view_cenas.pack_forget()
            self.view_bib.pack(fill="both", expand=True)

    def _construir_itens_cenas(self):
        for w in self.scroll_cenas.winfo_children():
            w.destroy()
        self._itens_ui_cenas.clear()

        if not self.repo.cenas:
            ctk.CTkLabel(
                self.scroll_cenas,
                text="Nenhuma cena encontrada no Trilha Playback.",
                text_color=TEMA["texto_secundario"],
                font=("Segoe UI", 12),
            ).pack(pady=16)
            return

        self.cena_selecionada_idx.set(0)
        c = self.config.campos

        for idx, cena in enumerate(self.repo.cenas):
            nome = cena.get(c["nome_cena"], f"Cena {idx + 1}")
            qtd = len(cena.get(c["itens_cena"], []))
            etiqueta_qtd = f"{qtd} {'música' if qtd == 1 else 'músicas'}"

            linha = ctk.CTkFrame(self.scroll_cenas, fg_color="transparent")
            linha.pack(fill="x", pady=2, padx=4)

            rb = ctk.CTkRadioButton(
                linha,
                text=nome,
                variable=self.cena_selecionada_idx,
                value=idx,
                fg_color=TEMA["ambar"],
                hover_color=TEMA["ambar_hover"],
                text_color=TEMA["texto_principal"],
                font=("Segoe UI", 12),
            )
            rb.pack(side="left")

            lbl_qtd = ctk.CTkLabel(
                linha,
                text=etiqueta_qtd,
                font=("Segoe UI", 11, "bold"),
                text_color=TEMA["ambar"],
            )
            lbl_qtd.pack(side="right", padx=6)

            # Permite selecionar a cena clicando em qualquer parte da linha
            linha.bind("<Button-1>", lambda _, i=idx: self.cena_selecionada_idx.set(i))
            lbl_qtd.bind("<Button-1>", lambda _, i=idx: self.cena_selecionada_idx.set(i))

            self._itens_ui_cenas.append((nome.lower(), linha))

    def _filtrar_lista_cenas(self):
        termo = self.entry_busca_cenas.get().lower().strip()
        for nome_lower, linha in self._itens_ui_cenas:
            if not termo or termo in nome_lower:
                if not linha.winfo_ismapped():
                    linha.pack(fill="x", pady=2, padx=4)
            else:
                if linha.winfo_ismapped():
                    linha.pack_forget()

    def _construir_itens_biblioteca(self):
        for w in self.scroll_bib.winfo_children():
            w.destroy()
        self._itens_ui_bib.clear()

        c = self.config.campos
        for m in self.repo.musicas:
            titulo = m.get(c["titulo_musica"], "Sem título")
            mid = m.get(c["id_musica"], titulo)
            if mid not in self.selecionados_bib:
                self.selecionados_bib[mid] = ctk.BooleanVar(value=False)

            pasta_norm = os.path.normcase(os.path.normpath(m.get(c["pasta_musica"], "")))
            versao = self.repo.versoes_por_pasta.get(pasta_norm, {})
            semitons = versao.get(c["semitons"], 0) or 0
            andamento = versao.get(c["andamento"], 1.0) or 1.0

            tom = calcular_novo_tom(m.get(c["tom_musica"], ""), semitons)
            bpm_str = formatar_bpm(m.get(c["bpm_musica"]), andamento)
            detalhes_tom = f"{tom}{f' ({semitons:+d}st)' if semitons != 0 else ''}"
            etiqueta = " • ".join(p for p in (detalhes_tom, bpm_str) if p)

            linha = ctk.CTkFrame(self.scroll_bib, fg_color="transparent")
            linha.pack(fill="x", pady=2, padx=4)

            ctk.CTkCheckBox(
                linha,
                text=titulo,
                variable=self.selecionados_bib[mid],
                fg_color=TEMA["ambar"],
                hover_color=TEMA["ambar_hover"],
                checkmark_color=TEMA["texto_on_ambar"],
                text_color=TEMA["texto_principal"],
                font=("Segoe UI", 12),
            ).pack(side="left")

            if etiqueta:
                ctk.CTkLabel(
                    linha,
                    text=etiqueta,
                    font=("Segoe UI", 11, "bold"),
                    text_color=TEMA["ambar"],
                ).pack(side="right", padx=6)

            self._itens_ui_bib.append((titulo.lower(), linha))

    def _filtrar_lista_biblioteca(self):
        termo = self.entry_busca_bib.get().lower().strip()
        for titulo_lower, linha in self._itens_ui_bib:
            if not termo or termo in titulo_lower:
                if not linha.winfo_ismapped():
                    linha.pack(fill="x", pady=2, padx=4)
            else:
                if linha.winfo_ismapped():
                    linha.pack_forget()

    def _recarregar_dados(self):
        avisos = self.repo.recarregar()
        self._construir_itens_cenas()
        self._construir_itens_biblioteca()
        self._filtrar_lista_cenas()
        self._filtrar_lista_biblioteca()
        self.log("Dados sincronizados com o Trilha Playback.")
        for av in avisos:
            self.log(f"[AVISO] {av}")

    def log(self, msg: str):
        def _append():
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")

        self.after(0, _append)

    def _atualizar_progresso(self, concluido: int, total: int):
        def _update():
            frac = (concluido / total) if total > 0 else 0.0
            pct = int(round(frac * 100))
            self.barra_progresso.definir(frac, f"{concluido} / {total} músicas  •  {pct}%")

        self.after(0, _update)

    def _escolher_pasta(self):
        if pasta := filedialog.askdirectory():
            self.pasta_saida = pasta
            self.btn_pasta.configure(text=f"📁  {os.path.basename(pasta) or pasta}")

    def _montar_fila(self) -> tuple[str, list[tuple[str, dict, dict]]] | None:
        c = self.config.campos
        if self.modo_atual == "Cena (Repertório)":
            if not self.repo.cenas:
                messagebox.showwarning("Aviso", "Nenhuma cena encontrada.")
                return None
            idx = min(self.cena_selecionada_idx.get(), len(self.repo.cenas) - 1)
            cena = self.repo.cenas[max(0, idx)]
            subpasta = re.sub(r'[<>:"/\\|?*]', "-", cena.get(c["nome_cena"], "Repertorio"))
            fila = [
                (f"{i:02d} - ", m_info, item)
                for i, item in enumerate(cena.get(c["itens_cena"], []), start=1)
                if (m_info := self.repo.musicas_por_id.get(item.get(c["id_musica_no_item"])))
            ]
            return subpasta, fila

        fila = []
        for m in self.repo.musicas:
            mid = m.get(c["id_musica"], m.get(c["titulo_musica"], ""))
            var = self.selecionados_bib.get(mid)
            if var and var.get():
                pasta_norm = os.path.normcase(os.path.normpath(m.get(c["pasta_musica"], "")))
                versao = self.repo.versoes_por_pasta.get(pasta_norm, {})
                fila.append(("", m, versao))

        if not fila:
            messagebox.showwarning("Aviso", "Marque pelo menos uma música na Biblioteca.")
            return None
        return "Biblioteca_Avulsas", fila

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
            rota_click_guide=self.seg_rota_cg.get(),
            rota_instrumental=self.seg_rota_inst.get(),
            eh_wav=fmt.startswith("WAV"),
            bitrate_mp3="320k" if "320" in fmt else "192k",
        )

        self.btn_exportar.configure(state="disabled", text="PROCESSANDO ÁUDIOS...")
        threading.Thread(target=self._executar_fila, args=(subpasta, fila, opcoes), daemon=True).start()

    def _executar_fila(self, subpasta: str, fila: list, opcoes: OpcoesExportacao):
        c = self.config.campos
        destino = os.path.join(self.pasta_saida, subpasta)
        os.makedirs(destino, exist_ok=True)

        total = len(fila)
        self._atualizar_progresso(0, total)
        self.log(f"\n▶ Exportando {total} música(s) | {'WAV' if opcoes.eh_wav else 'MP3 ' + opcoes.bitrate_mp3}")

        lock_contador = threading.Lock()
        estado = {"concluidas": 0, "sucessos": 0}

        def _processar_item(indice: int, item_fila: tuple):
            prefixo, musica_info, config_item = item_fila
            titulo = musica_info.get(c["titulo_musica"], f"Musica_{indice}")
            semitons = config_item.get(c["semitons"], 0) or 0
            andamento = config_item.get(c["andamento"], 1.0) or 1.0
            tom = calcular_novo_tom(musica_info.get(c["tom_musica"], ""), semitons)
            bpm_str = formatar_bpm(musica_info.get(c["bpm_musica"]), andamento)

            info_log = ", ".join(p for p in (f"Tom: {tom}" if tom else "", f"{semitons:+d} st", bpm_str) if p)
            self.log(f"[{indice}/{total}] {titulo} ({info_log})...")

            try:
                arquivo_gerado = self.engine.processar_musica(
                    prefixo, musica_info, config_item, destino, opcoes, on_status=self.log
                )
                with lock_contador:
                    estado["sucessos"] += 1
                    estado["concluidas"] += 1
                    self._atualizar_progresso(estado["concluidas"], total)
                self.log(f"   ✓ {arquivo_gerado}")
            except Exception as erro:
                with lock_contador:
                    estado["concluidas"] += 1
                    self._atualizar_progresso(estado["concluidas"], total)
                self.log(f"   ✕ FALHA em '{titulo}': {erro}")

        # Processa múltiplas músicas em paralelo aproveitando RAM e núcleos disponíveis
        workers_musicas = min(total, 2 if (os.cpu_count() or 2) <= 4 else 3)
        with ThreadPoolExecutor(max_workers=workers_musicas) as pool:
            for idx, item in enumerate(fila, start=1):
                pool.submit(_processar_item, idx, item)

        sucessos = estado["sucessos"]
        self.log(f"\nCONCLUÍDO! {sucessos}/{total} música(s) exportada(s).")
        self.after(0, lambda: self._finalizar_ui(sucessos, total, destino))

    def _finalizar_ui(self, sucessos: int, total: int, destino: str):
        self.btn_exportar.configure(state="normal", text="EXPORTAR ÁUDIOS")
        if sucessos > 0:
            messagebox.showinfo("Exportação Concluída", f"{sucessos} de {total} música(s) salva(s) em:\n{destino}")
            os.startfile(destino)


if __name__ == "__main__":
    app = AppExportador()
    app.mainloop()