import os
import shutil
import zipfile
import subprocess
import sys
import json
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurações de Pastas (Adicionado minihooks)
DIRS = ["uploads/minihooks", "uploads/hooks", "uploads/bodies", "uploads/ctas", "output"]
for d in DIRS:
    os.makedirs(d, exist_ok=True)

status_processamento = {"status": "aguardando", "total": 0, "progresso": 0, "log": []}

# Modelo para receber as opções do Frontend
class JobSettings(BaseModel):
    usar_minihook: bool
    usar_transicao: bool

def log_print(msg):
    print(msg, flush=True)
    status_processamento["log"].append(msg)

def limpar_nome(nome):
    return nome.split(' -')[0].strip()

def get_duration(file_path):
    """Pega a duração exata do vídeo em segundos usando ffprobe"""
    try:
        cmd = [
            "ffprobe", "-v", "error", 
            "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def processar_videos_ffmpeg(settings: JobSettings):
    global status_processamento
    status_processamento["status"] = "processando"
    status_processamento["log"] = []
    
    log_print(f"--- INICIANDO (MiniHook: {settings.usar_minihook} | Transição: {settings.usar_transicao}) ---")
    
    # Listar arquivos
    minihooks = sorted([f for f in os.listdir("uploads/minihooks") if f.endswith((".mp4", ".mov"))]) if settings.usar_minihook else []
    hooks = sorted([f for f in os.listdir("uploads/hooks") if f.endswith((".mp4", ".mov"))])[:5]
    bodies = sorted([f for f in os.listdir("uploads/bodies") if f.endswith((".mp4", ".mov"))])[:5]
    ctas = sorted([f for f in os.listdir("uploads/ctas") if f.endswith((".mp4", ".mov"))])[:5]
    
    # Se MiniHook estiver ativado mas a pasta estiver vazia, avisa e segue sem
    if settings.usar_minihook and not minihooks:
        log_print("⚠️ AVISO: Opção MiniHook ativada, mas nenhum arquivo encontrado. Gerando sem MiniHooks.")
        minihooks = [None] # Hack para o loop rodar 1 vez sem MH
    elif not settings.usar_minihook:
        minihooks = [None] # Loop roda 1 vez sem MH

    total = len(minihooks) * len(hooks) * len(bodies) * len(ctas)
    if total == 0:
        log_print("❌ Erro: Faltam arquivos principais (Hooks, Bodies ou CTAs).")
        status_processamento["status"] = "erro"
        return

    status_processamento["total"] = total
    count = 0
    generated_files = []

    for mh in minihooks:
        for h in hooks:
            for b in bodies:
                for c in ctas:
                    try:
                        # Monta a lista de inputs para este vídeo específico
                        inputs = []
                        nomes_partes = []
                        
                        # Adiciona MH se existir
                        if mh:
                            inputs.append(os.path.abspath(os.path.join("uploads/minihooks", mh)))
                            nomes_partes.append(limpar_nome(mh))
                        
                        # Adiciona o resto
                        inputs.append(os.path.abspath(os.path.join("uploads/hooks", h)))
                        inputs.append(os.path.abspath(os.path.join("uploads/bodies", b)))
                        inputs.append(os.path.abspath(os.path.join("uploads/ctas", c)))
                        
                        nomes_partes.extend([limpar_nome(h), limpar_nome(b), limpar_nome(c)])
                        
                        nome_final = f"AD{count+1}-" + "-".join(nomes_partes) + ".mp4"
                        path_out = os.path.abspath(os.path.join("output", nome_final))
                        
                        log_print(f"[{count+1}/{total}] Renderizando: {nome_final}")

                        # --- CONSTRUÇÃO DO COMANDO FFMPEG ---
                        cmd = ["ffmpeg", "-y"]
                        for inp in inputs:
                            cmd.extend(["-i", inp])

                        filter_complex = ""
                        
                        # 1. Normalização (Scale)
                        # Redimensiona todos para 720x1280 para evitar erros de concatenação
                        for i in range(len(inputs)):
                            filter_complex += f"[{i}:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
                            # Se não tiver transição, precisamos preparar o áudio também para o concat simples
                            if not settings.usar_transicao:
                                pass 

                        # 2. Lógica de Junção
                        if settings.usar_transicao:
                            # Lógica Complexa de XFADE (Dissolve)
                            # Precisamos calcular os offsets (quando começa cada transição)
                            duracao_transicao = 0.5 # 0.5 segundos de transição
                            offset_atual = 0
                            
                            # Pega durações
                            duracoes = [get_duration(inp) for inp in inputs]
                            
                            # Inicia com o primeiro vídeo
                            v_prev = "[v0]"
                            a_prev = f"[0:a]"
                            
                            for i in range(1, len(inputs)):
                                # O offset é cumulativo: offset anterior + duração do vídeo anterior - duração da transição
                                offset_atual += duracoes[i-1] - duracao_transicao
                                if offset_atual < 0: offset_atual = 0 # Segurança
                                
                                # Video Mix (xfade)
                                filter_complex += f"{v_prev}[v{i}]xfade=transition=fade:duration={duracao_transicao}:offset={offset_atual}[vmix{i}];"
                                v_prev = f"[vmix{i}]"
                                
                                # Audio Mix (acrossfade) - Não usa offset, usa overlap
                                # O acrossfade consome o stream, então encadeamos
                                filter_complex += f"{a_prev}[{i}:a]acrossfade=d={duracao_transicao}:c1=tri:c2=tri[amix{i}];"
                                a_prev = f"[amix{i}]"
                            
                            # Mapeia o resultado final
                            map_v = v_prev
                            map_a = a_prev
                            
                        else:
                            # Lógica Simples de CONCAT (Corte Seco - Mais rápido e seguro)
                            concat_v = ""
                            concat_a = ""
                            for i in range(len(inputs)):
                                concat_v += f"[v{i}]"
                                concat_a += f"[{i}:a]"
                            
                            filter_complex += f"{concat_v}{concat_a}concat=n={len(inputs)}:v=1:a=1[v][a]"
                            map_v = "[v]"
                            map_a = "[a]"

                        cmd.extend([
                            "-filter_complex", filter_complex,
                            "-map", map_v, 
                            "-map", map_a,
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-r", "30",
                            path_out
                        ])

                        # Executa
                        processo = subprocess.run(cmd, stdout=sys.stdout, stderr=sys.stderr, timeout=400)
                        
                        if processo.returncode == 0:
                            generated_files.append(path_out)
                            log_print(f"✅ Sucesso")
                        else:
                            log_print(f"❌ Erro no FFmpeg")

                    except Exception as e:
                        log_print(f"❌ Erro Crítico: {str(e)}")
                    
                    count += 1
                    status_processamento["progresso"] = count

    # ZIP Final
    try:
        log_print("Compactando...")
        zip_path = "output/todos_ads.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for file in generated_files:
                zipf.write(file, os.path.basename(file))
        status_processamento["status"] = "concluido"
        status_processamento["download_url"] = "/download/todos_ads.zip"
        log_print("🏁 TUDO PRONTO!")
    except Exception as e:
        status_processamento["status"] = "erro"
        status_processamento["mensagem"] = str(e)

@app.post("/upload/{tipo}")
async def upload_file(tipo: str, file: UploadFile):
    filename = file.filename.replace(" ", "_")
    path = f"uploads/{tipo}/{filename}"
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": filename}

@app.post("/iniciar")
async def start_processing(settings: JobSettings, background_tasks: BackgroundTasks):
    background_tasks.add_task(processar_videos_ffmpeg, settings)
    return {"message": "Iniciado"}

@app.get("/status")
def get_status():
    return status_processamento

@app.get("/download/{filename}")
def download_file(filename: str):
    return FileResponse(f"output/{filename}")
