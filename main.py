import os
import shutil
import zipfile
from fastapi import FastAPI, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from moviepy.editor import VideoFileClip, concatenate_videoclips

app = FastAPI()

# Configuração de CORS (Permite que seu Front no Vercel fale com esse Back)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, troque "*" pela URL do seu Front
    allow_methods=["*"],
    allow_headers=["*"],
)

# Diretórios
DIRS = ["uploads/hooks", "uploads/bodies", "uploads/ctas", "output"]
for d in DIRS:
    os.makedirs(d, exist_ok=True)

# Variável global simples para status (em prod, use um banco de dados)
status_processamento = {"status": "aguardando", "total": 0, "progresso": 0, "log": []}

def limpar_nome(nome):
    return nome.split(' -')[0].strip()

def processar_videos():
    global status_processamento
    status_processamento["status"] = "processando"
    status_processamento["log"] = []
    
    hooks = sorted([f for f in os.listdir("uploads/hooks") if f.endswith(".mp4")])[:5]
    bodies = sorted([f for f in os.listdir("uploads/bodies") if f.endswith(".mp4")])[:5]
    ctas = sorted([f for f in os.listdir("uploads/ctas") if f.endswith(".mp4")])[:5]
    
    total = len(hooks) * len(bodies) * len(ctas)
    status_processamento["total"] = total
    count = 0
    generated_files = []

    for h in hooks:
        for b in bodies:
            for c in ctas:
                try:
                    clip1 = VideoFileClip(f"uploads/hooks/{h}")
                    clip2 = VideoFileClip(f"uploads/bodies/{b}")
                    clip3 = VideoFileClip(f"uploads/ctas/{c}")
                    
                    final = concatenate_videoclips([clip1, clip2, clip3], method="compose")
                    
                    nome_final = f"AD{count+1}-{limpar_nome(h)}-{limpar_nome(b)}-{limpar_nome(c)}.mp4"
                    path = f"output/{nome_final}"
                    
                    final.write_videofile(path, codec='libx264', audio_codec='aac', preset='ultrafast', threads=4, logger=None)
                    
                    generated_files.append(path)
                    
                    # Log e Progresso
                    msg = f"Gerado: {nome_final}"
                    status_processamento["log"].append(msg)
                    print(msg)
                    
                    clip1.close(); clip2.close(); clip3.close(); final.close()
                    count += 1
                    status_processamento["progresso"] = count
                    
                except Exception as e:
                    status_processamento["log"].append(f"Erro: {str(e)}")

    # Criar ZIP final
    zip_path = "output/todos_ads.zip"
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for file in generated_files:
            zipf.write(file, os.path.basename(file))
            
    status_processamento["status"] = "concluido"
    status_processamento["download_url"] = "/download/todos_ads.zip"

@app.post("/upload/{tipo}")
async def upload_file(tipo: str, file: UploadFile):
    path = f"uploads/{tipo}/{file.filename}"
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"filename": file.filename}

@app.post("/iniciar")
async def start_processing(background_tasks: BackgroundTasks):
    background_tasks.add_task(processar_videos)
    return {"message": "Processamento iniciado"}

@app.get("/status")
def get_status():
    return status_processamento

@app.get("/download/{filename}")
def download_file(filename: str):
    return FileResponse(f"output/{filename}")