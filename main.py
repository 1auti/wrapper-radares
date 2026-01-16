"""
Wrapper para pipeline de radares.
Recibe ZIP con múltiples presunciones, divide, guarda en disco y envía al CLOUD.
"""
from fastapi import FastAPI, UploadFile, HTTPException
from pydantic import BaseModel
from pathlib import Path
import zipfile
import json
import io
import httpx
import os
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Wrapper ZIP Radares")

CLOUD_URL = os.getenv("CLOUD_URL", "https://ingesta-1042206377352.southamerica-east1.run.app/api/Presuncion/radares/zip/simple")
CLOUD_AUTH = os.getenv("CLOUD_AUTH", "")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
CARPETA_SALIDA = os.getenv("CARPETA_SALIDA", "/tmp/salida_radares")


class Resultado(BaseModel):
    total: int
    exitosas: int
    fallidas: int
    errores: list[str]
    carpeta_salida: str


def extraer_info_radar(nombre_json: str) -> tuple[str, str, str]:
    """
    Extrae número de radar, fecha y serie del equipo del nombre del JSON.
    Ejemplo: 'TS_CONTROL_X_0061 20260105.json' -> ('0061', '20260105', 'TS_CONTROL_X_0061')
    """
    nombre = nombre_json.replace('.json', '').split('/')[-1]
    partes = nombre.replace('TS_CONTROL_X_', '').split(' ')

    if len(partes) >= 2:
        numero_radar = partes[0]
        fecha = partes[1]
        serie_equipo = f"TS_CONTROL_X_{numero_radar}"
    else:
        numero_radar = "0000"
        fecha = "00000000"
        serie_equipo = "TS_CONTROL_X_0000"

    return numero_radar, fecha, serie_equipo


def extraer_fecha_infraccion(nombre_original: str) -> str:
    """
    Extrae la fecha de infracción del nombre del archivo original.
    Ejemplo: '0061-01-05-2026-23-47-26-411-2-.jpg' -> '2026-01-05 23:47:26'
    """
    try:
        partes = nombre_original.replace('.jpg', '').split('-')
        if len(partes) >= 7:
            mes = partes[1]
            dia = partes[2]
            anio = partes[3]
            hora = partes[4]
            minuto = partes[5]
            segundo = partes[6]
            return f"{anio}-{mes}-{dia} {hora}:{minuto}:{segundo}"
    except:
        pass
    return ""


def limpiar_velocidad(velocidad: str) -> str:
    """
    Extrae solo el número de velocidad del campo.
    Ejemplo: 'Velocidad: 87,17 km/h' -> '87,17'
    """
    if not velocidad or "Velocidad" not in velocidad:
        return velocidad

    try:
        # Quitar "Velocidad: " y " km/h"
        valor = velocidad.replace("Velocidad:", "").replace("km/h", "").strip()
        return valor
    except:
        return velocidad


@app.post("/api/test")
async def test_dividir(file: UploadFile):
    """
    Endpoint de prueba: divide el ZIP y guarda localmente SIN enviar al CLOUD.
    """
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un ZIP")

    zip_bytes = await file.read()
    archivos_guardados, numero_radar, fecha, serie_equipo = dividir_y_guardar(zip_bytes)

    ejemplo_json = None
    if archivos_guardados:
        with zipfile.ZipFile(archivos_guardados[0], 'r') as zf:
            ejemplo_json = json.loads(zf.read("presuncion.json"))

    return {
        "mensaje": "ZIPs generados (NO enviados al CLOUD)",
        "total": len(archivos_guardados),
        "serie_equipo": serie_equipo,
        "carpeta_salida": CARPETA_SALIDA,
        "ejemplo_json": ejemplo_json
    }


@app.post("/api/procesar", response_model=Resultado)
async def procesar_zip(file: UploadFile):
    """Recibe ZIP, divide, guarda y envía al CLOUD."""
    logger.info(f"=== Recibido archivo: {file.filename} ===")

    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un ZIP")

    zip_bytes = await file.read()
    logger.info(f"Tamaño del ZIP: {len(zip_bytes)} bytes")

    logger.info("Paso 1: Dividiendo ZIP...")
    archivos_guardados, numero_radar, fecha, serie_equipo = dividir_y_guardar(zip_bytes)
    logger.info(f"Guardados {len(archivos_guardados)} archivos")

    logger.info("Paso 2: Enviando al CLOUD...")
    resultado = await enviar_desde_disco(archivos_guardados)

    logger.info(f"=== Resultado: {resultado.exitosas} exitosas, {resultado.fallidas} fallidas ===")
    return resultado


def dividir_y_guardar(zip_bytes: bytes) -> tuple[list[str], str, str, str]:
    """Divide el ZIP y guarda cada presunción en disco."""

    Path(CARPETA_SALIDA).mkdir(parents=True, exist_ok=True)

    contenido = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
        for nombre in zf.namelist():
            if not nombre.endswith('/'):
                contenido[nombre] = zf.read(nombre)

    archivo_json = next((n for n in contenido if n.endswith('.json')), None)
    if not archivo_json:
        raise HTTPException(status_code=400, detail="No se encontró JSON en el ZIP")

    numero_radar, fecha, serie_equipo = extraer_info_radar(archivo_json)

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

    archivos_guardados = []

    for idx, presuncion in enumerate(presunciones):
        nombre_archivo = f"TS_CONTROL_X_{numero_radar} {fecha} {idx:04d}.zip"
        ruta_completa = Path(CARPETA_SALIDA) / nombre_archivo

        # Agregar campos adicionales
        presuncion_enriquecida = presuncion.copy()
        presuncion_enriquecida["SerieEquipo"] = serie_equipo
        presuncion_enriquecida["FechaInfraccion"] = extraer_fecha_infraccion(presuncion.get("Original", ""))
        presuncion_enriquecida["Velocidad"] = limpiar_velocidad(presuncion.get("Velocidad", ""))

        with zipfile.ZipFile(ruta_completa, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("presuncion.json", json.dumps(presuncion_enriquecida, ensure_ascii=False))

            img_original = presuncion.get("Original", "")
            if img_original and img_original in contenido:
                zf.writestr(img_original, contenido[img_original])

            img_recorte = presuncion.get("Recorte", "")
            if img_recorte and img_recorte in contenido:
                zf.writestr(img_recorte, contenido[img_recorte])

        archivos_guardados.append(str(ruta_completa))

    return archivos_guardados, numero_radar, fecha, serie_equipo


async def enviar_desde_disco(archivos: list[str]) -> Resultado:
    """Lee los ZIPs del disco y los envía al CLOUD."""

    exitosas = 0
    fallidas = 0
    errores = []
    total = len(archivos)

    headers = {}
    if CLOUD_AUTH:
        headers["Authorization"] = CLOUD_AUTH

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for idx, ruta_archivo in enumerate(archivos):
            nombre = Path(ruta_archivo).name
            logger.info(f"Enviando {idx+1}/{total}: {nombre}")
            try:
                with open(ruta_archivo, 'rb') as f:
                    zip_bytes = f.read()

                files = {"file": (nombre, zip_bytes, "application/zip")}
                response = await client.post(CLOUD_URL, files=files, headers=headers)

                if response.status_code >= 400:
                    raise Exception(f"HTTP {response.status_code}: {response.text[:100]}")

                os.remove(ruta_archivo)
                exitosas += 1
                logger.info(f"  ✓ OK")

            except Exception as e:
                fallidas += 1
                errores.append(f"{nombre}: {str(e)}")
                logger.error(f"  ✗ Error: {str(e)}")

    return Resultado(
        total=total,
        exitosas=exitosas,
        fallidas=fallidas,
        errores=errores,
        carpeta_salida=CARPETA_SALIDA
    )


@app.post("/api/reenviar")
async def reenviar_pendientes():
    """Reenvía los ZIPs que quedaron en la carpeta."""
    archivos = list(Path(CARPETA_SALIDA).glob("*.zip"))

    if not archivos:
        return {"mensaje": "No hay archivos pendientes", "carpeta": CARPETA_SALIDA}

    resultado = await enviar_desde_disco([str(a) for a in archivos])
    return resultado


@app.get("/health")
def health():
    pendientes = len(list(Path(CARPETA_SALIDA).glob("*.zip"))) if Path(CARPETA_SALIDA).exists() else 0
    return {
        "status": "ok",
        "cloud_url": CLOUD_URL,
        "carpeta_salida": CARPETA_SALIDA,
        "archivos_pendientes": pendientes
    }