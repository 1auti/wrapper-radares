"""
Wrapper para pipeline de radares.
Recibe ZIP con múltiples presunciones, divide y envía cada una al CLOUD.
"""

from fastapi import FastAPI, UploadFile, HTTPException
from pydantic import BaseModel
import zipfile
import json
import io
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Wrapper ZIP Radares")

# URL del endpoint CLOUD (configurable via .env)
CLOUD_URL = os.getenv("CLOUD_URL", "http://localhost:8080/api/recibir")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))


class Resultado(BaseModel):
    total: int
    exitosas: int
    fallidas: int
    errores: list[str]


@app.post("/api/procesar", response_model=Resultado)
async def procesar_zip(file: UploadFile):
    """
    Recibe ZIP del pipeline, divide por presunción y envía cada uno al CLOUD.
    """
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un ZIP")

    zip_bytes = await file.read()
    resultado = await dividir_y_enviar(zip_bytes)
    return resultado


async def dividir_y_enviar(zip_bytes: bytes) -> Resultado:
    """Divide el ZIP y envía cada presunción al CLOUD."""

    # Extraer contenido del ZIP
    contenido = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
        for nombre in zf.namelist():
            if not nombre.endswith('/'):
                contenido[nombre] = zf.read(nombre)

    # Buscar y parsear JSON
    archivo_json = next((n for n in contenido if n.endswith('.json')), None)
    if not archivo_json:
        raise HTTPException(status_code=400, detail="No se encontró JSON en el ZIP")

    # Decodificar JSON (varios encodings)
    json_bytes = contenido[archivo_json]
    json_texto = None
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            json_texto = json_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if json_texto is None:
        raise HTTPException(status_code=400, detail="No se pudo decodificar el JSON")

    datos = json.loads(json_texto)
    presunciones = datos.get("Presunciones", [])

    # Procesar y enviar cada presunción
    exitosas = 0
    fallidas = 0
    errores = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for idx, presuncion in enumerate(presunciones):
            lectura = presuncion.get("Lectura", "SIN_LECTURA")
            try:
                # Crear ZIP individual
                zip_individual = crear_zip_individual(presuncion, contenido)

                # Enviar al CLOUD
                nombre_archivo = f"presuncion_{idx:04d}_{lectura}.zip"
                await enviar_a_cloud(client, zip_individual, nombre_archivo)
                exitosas += 1
            except Exception as e:
                fallidas += 1
                errores.append(f"{idx}_{lectura}: {str(e)}")

    return Resultado(
        total=len(presunciones),
        exitosas=exitosas,
        fallidas=fallidas,
        errores=errores
    )


def crear_zip_individual(presuncion: dict, contenido_original: dict[str, bytes]) -> bytes:
    """Crea ZIP con una presunción y sus imágenes."""
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # JSON de la presunción
        zf.writestr("presuncion.json", json.dumps(presuncion, ensure_ascii=False, indent=2))

        # Imagen Original
        img_original = presuncion.get("Original", "")
        if img_original and img_original in contenido_original:
            zf.writestr(img_original, contenido_original[img_original])

        # Imagen Recorte
        img_recorte = presuncion.get("Recorte", "")
        if img_recorte and img_recorte in contenido_original:
            zf.writestr(img_recorte, contenido_original[img_recorte])

    return buffer.getvalue()


async def enviar_a_cloud(client: httpx.AsyncClient, zip_bytes: bytes, nombre: str):
    """Envía el ZIP individual al endpoint CLOUD."""
    files = {"file": (nombre, zip_bytes, "application/zip")}
    response = await client.post(CLOUD_URL, files=files)

    if response.status_code >= 400:
        raise Exception(f"HTTP {response.status_code}: {response.text[:100]}")


@app.get("/health")
def health():
    return {"status": "ok", "cloud_url": CLOUD_URL}