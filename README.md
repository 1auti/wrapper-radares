# Wrapper ZIP Radares

Microservicio que recibe ZIPs del pipeline de radares, los divide en presunciones individuales y las envía al CLOUD.

## Flujo

```
PIPELINE ──POST ZIP──> WRAPPER ──POST cada presunción──> CLOUD
```

## Requisitos

- Python 3.12+
- pip

## Instalación

```bash
# Clonar/crear carpeta del proyecto
mkdir wrapper-radares && cd wrapper-radares

# Crear entorno virtual
python3.12 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install fastapi uvicorn python-multipart httpx python-dotenv
```

## Configuración

Crear archivo `.env` en la raíz del proyecto:

```env
# URL del endpoint CLOUD donde se envían las presunciones
CLOUD_URL=http://direccion-cloud:8080/api/recibir

# Timeout en segundos para cada envío
HTTP_TIMEOUT=30
```

## Ejecución

```bash
# Desarrollo
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Producción
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Endpoints

### POST /api/procesar

Recibe un ZIP del pipeline y procesa todas las presunciones.

**Request:**
- Content-Type: `multipart/form-data`
- Body: archivo ZIP con el campo `file`

**Response:**
```json
{
  "total": 253,
  "exitosas": 250,
  "fallidas": 3,
  "errores": [
    "45_ABC123: HTTP 500: Error interno",
    "120_XYZ789: Connection timeout"
  ]
}
```

**Ejemplo con curl:**
```bash
curl -X POST "http://localhost:8000/api/procesar" \
  -F "file=@/ruta/al/archivo.zip"
```

### GET /health

Health check del servicio.

**Response:**
```json
{
  "status": "ok",
  "cloud_url": "http://direccion-cloud:8080/api/recibir"
}
```

## Estructura del ZIP de entrada

El ZIP del pipeline debe contener:

```
TS_CONTROL_X_0061 20260105.zip
├── TS_CONTROL_X_0061 20260105.json    # JSON con array "Presunciones"
├── 0061-01-05-2026-00-01-54-081-2-.jpg        # Imágenes originales
├── 0061-01-05-2026-00-01-54-081-2--plate.jpg  # Recortes de patente
└── ...
```

**Estructura del JSON:**
```json
{
  "Presunciones": [
    {
      "Lectura": "ABC123",
      "Confidence": 85.5,
      "Original": "0061-01-05-2026-00-01-54-081-2-.jpg",
      "Recorte": "0061-01-05-2026-00-01-54-081-2--plate.jpg",
      "Velocidad": "Velocidad: 95,45 km/h"
    }
  ]
}
```

## ZIP de salida (enviado al CLOUD)

Cada presunción se envía como un ZIP individual:

```
presuncion_0001_ABC123.zip
├── presuncion.json           # Datos de la presunción
├── 0061-01-05-2026-...jpg    # Imagen original
└── 0061-01-05-2026-...-plate.jpg  # Recorte patente
```

## Swagger UI

Documentación interactiva disponible en:

```
http://localhost:8000/docs
```

## Estructura del proyecto

```
wrapper-radares/
├── main.py           # Código principal
├── .env              # Configuración (no commitear)
├── requirements.txt  # Dependencias
└── README.md         # Esta documentación
```

## requirements.txt

```
fastapi
uvicorn[standard]
python-multipart
httpx
python-dotenv
```