import os
import shutil
import zipfile
import gc
from fastapi import FastAPI, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from moviepy.editor import VideoFileClip, concatenate_videoclips

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Criar pastas ao iniciar
DIRS = ["uploads/hooks", "uploads/bodies", "uploads/ctas", "output"]
for d in DIRS:
    os.makedirs(d, exist_ok=True)

# Status global
status_processamento = {"status": "aguardando", "total": 0, "progresso": 0, "log": []}

def log_print(msg):
    """Função para forçar o log a aparecer imediatamente no Render"""
    print(msg, flush=True)
    status_processamento["log"].append(msg)

def limpar_nome(nome):
    return nome.split(' -')[0].strip()

def processar_videos():
    global status_processamento
    status_processamento["status"] = "processando"
    status_processamento["log"] = []
    
    log_print("--- INICIANDO PROCESSAMENTO ---")
    
    # Verifica se há arquivos
    hooks = sorted([f for f in os.listdir("uploads/hooks") if f.endswith((".mp4", ".mov"))])
    bodies = sorted([f for f in os.listdir("uploads/bodies") if f.endswith((".mp4", ".mov"))])
    ctas = sorted([f for f in os.listdir("uploads/ctas") if f.endswith((".mp4", ".mov"))])
    
    if not hooks or not bodies or not ctas:
        log_print("ERRO: Faltam arquivos em alguma das pastas!")
        status_processamento["status"] = "erro"
        status_processamento["mensagem"] = "Faltam arquivos. Faça o upload novamente."
        return

    # Limita a 5 para teste seguro
    hooks = hooks[:5]
    bodies = bodies[:5]
    ctas = ctas[:5]
    
    total = len(hooks) * len(bodies) * len(ctas)
    status_processamento["total"] = total
    log_print(f"Total de combinações a gerar: {total}")
    
    count = 0
    generated_files = []

    for h in hooks:
        for b in bodies:
            for c in ctas:
                clip1 = None; clip2 = None; clip3 = None; final = None
                try:
                    p_h = os.path.join("uploads/hooks", h)
                    p_b = os.path.join("uploads/bodies", b)
                    p_c = os.path.join("uploads/ctas", c)
                    
                    log_print(f"Combinando: {h} + {b} + {c}")

                    clip1 = VideoFileClip(p_h)
                    clip2 = VideoFileClip(p_b)
                    clip3 = VideoFileClip(p_c)
                    
                    # Redimensiona para garantir compatibilidade (evita erros de tamanho)
                    # clip2 = clip2.resize(clip1.size)
                    # clip3 = clip3.resize(clip1.size)

                    final = concatenate_videoclips([clip1, clip2, clip3], method="compose")
                    
                    nome_final = f"AD{count+1}-{limpar_nome(h)}-{limpar_nome(b)}-{limpar_nome(c)}.mp4"
                    path_out = os.path.join("output", nome_final)
                    
                    # threads=1 e preset=ultrafast são CRUCIAIS para não cair o servidor Free
                    final.write_videofile(
                        path_out, 
                        codec='libx264', 
                        audio_codec='aac', 
                        preset='ultrafast', 
                        threads=1, 
                        logger=None
                    )
                    
                    generated_files.append(path_out)
                    log_print(f"Sucesso: {nome_final}")
                    
                except Exception as e:
                    err_msg = f"Erro ao criar AD{count+1}: {str(e)}"
                    log_print(err_msg)
                
                finally:
                    # Limpeza agressiva de memória
                    if clip1: clip1.close()
                    if clip2: clip2.close()
                    if clip3: clip3.close()
                    if final: final.close()
                    gc.collect()

                count += 1
                status_processamento["progresso"] = count

    # Criar ZIP
    try:
        log_print("Criando arquivo ZIP...")
        zip_path = "output/todos_ads.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for file in generated_files:
                zipf.write(file, os.path.basename(file))
        
        log_print("Processo Concluído!")
        status_processamento["status"] = "concluido"
        status_processamento["download_url"] = "/download/todos_ads.zip"
    except Exception as e:
        log_print(f"Erro ao zipar: {e}")
        status_processamento["status"] = "erro"
        status_processamento["mensagem"] = str(e)

@app.post("/upload/{tipo}")
async def upload_file(tipo: str, file: UploadFile):
    path = f"uploads/{tipo}/{file.filename}"
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename}

@app.post("/iniciar")
async def start_processing(background_tasks: BackgroundTasks):
    background_tasks.add_task(processar_videos)
    return {"message": "Iniciado"}

@app.get("/status")
def get_status():
    return status_processamento

@app.get("/download/{filename}")
def download_file(filename: str):
    return FileResponse(f"output/{filename}")
