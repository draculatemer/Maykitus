import os
import shutil
import zipfile
import subprocess # Vamos usar isso no lugar do MoviePy
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

# Criar pastas
DIRS = ["uploads/hooks", "uploads/bodies", "uploads/ctas", "output"]
for d in DIRS:
    os.makedirs(d, exist_ok=True)

status_processamento = {"status": "aguardando", "total": 0, "progresso": 0, "log": []}

def log_print(msg):
    print(msg, flush=True)
    status_processamento["log"].append(msg)

def limpar_nome(nome):
    return nome.split(' -')[0].strip()

def processar_videos_ffmpeg():
    global status_processamento
    status_processamento["status"] = "processando"
    status_processamento["log"] = []
    
    log_print("--- INICIANDO MODO TURBO (FFmpeg) ---")
    
    hooks = sorted([f for f in os.listdir("uploads/hooks") if f.endswith((".mp4", ".mov"))])
    bodies = sorted([f for f in os.listdir("uploads/bodies") if f.endswith((".mp4", ".mov"))])
    ctas = sorted([f for f in os.listdir("uploads/ctas") if f.endswith((".mp4", ".mov"))])
    
    # Limite de segurança para teste (pode aumentar depois)
    hooks = hooks[:5]
    bodies = bodies[:5]
    ctas = ctas[:5]
    
    total = len(hooks) * len(bodies) * len(ctas)
    status_processamento["total"] = total
    
    count = 0
    generated_files = []

    for h in hooks:
        for b in bodies:
            for c in ctas:
                try:
                    # Caminhos absolutos para o FFmpeg não se perder
                    p_h = os.path.abspath(os.path.join("uploads/hooks", h))
                    p_b = os.path.abspath(os.path.join("uploads/bodies", b))
                    p_c = os.path.abspath(os.path.join("uploads/ctas", c))
                    
                    nome_final = f"AD{count+1}-{limpar_nome(h)}-{limpar_nome(b)}-{limpar_nome(c)}.mp4"
                    path_out = os.path.abspath(os.path.join("output", nome_final))
                    
                    log_print(f"[{count+1}/{total}] Processando: {nome_final}")

                    # COMANDO MÁGICO DO FFMPEG (Usa quase zero memória RAM do Python)
                    # Ele redimensiona tudo para HD (1280x720) para garantir que não trave
                    comando = [
                        "ffmpeg", "-y",
                        "-i", p_h,
                        "-i", p_b,
                        "-i", p_c,
                        "-filter_complex", 
                        "[0:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2[v0];"
                        "[1:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2[v1];"
                        "[2:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2[v2];"
                        "[v0][0:a][v1][1:a][v2][2:a]concat=n=3:v=1:a=1[v][a]",
                        "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        path_out
                    ]

                    # Executa o comando
                    resultado = subprocess.run(comando, capture_output=True, text=True)
                    
                    if resultado.returncode == 0:
                        generated_files.append(path_out)
                        log_print(f"✅ Sucesso: {nome_final}")
                    else:
                        log_print(f"❌ Erro no FFmpeg: {resultado.stderr}")

                except Exception as e:
                    log_print(f"❌ Erro Crítico: {str(e)}")
                
                count += 1
                status_processamento["progresso"] = count

    # Criar ZIP
    try:
        log_print("Compactando arquivos...")
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
    # Limpa o nome do arquivo para evitar erros com espaços e caracteres estranhos
    filename = file.filename.replace(" ", "_")
    path = f"uploads/{tipo}/{filename}"
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": filename}

@app.post("/iniciar")
async def start_processing(background_tasks: BackgroundTasks):
    background_tasks.add_task(processar_videos_ffmpeg)
    return {"message": "Iniciado"}

@app.get("/status")
def get_status():
    return status_processamento

@app.get("/download/{filename}")
def download_file(filename: str):
    return FileResponse(f"output/{filename}")
