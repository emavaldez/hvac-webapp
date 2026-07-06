# HVAC Web App

Interfaz web con login para consultar al agente HVAC de Hermes.

## Qué es

App web (FastAPI) que permite a usuarios autorizados chatear con un agente Hermes limitado a consultas HVAC. Los usuarios no tienen acceso al agente completo — solo pueden enviar mensajes y ver su historial.

## Deploy en NaN Cloud Apps

1. Crear repo en GitHub y push
2. En NaN Cloud: reclamar Space Basic gratis
3. New App → conectar repo → rama main
4. Marcar "Expose over HTTP" → puerto 8080
5. Configurar env vars (ver abajo)
6. Deploy

## Variables de entorno

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `HERMES_API_URL` | URL del Hermes API Server (con /v1) | `http://hermes-internal:8642/v1` |
| `HERMES_API_KEY` | API key del Hermes API Server | `tu-secret-key` |
| `HERMES_MODEL` | Nombre del modelo en Hermes | `hermes-agent` |
| `JWT_SECRET` | Secret para firmar tokens | string aleatorio largo |
| `USERS` | Usuarios en JSON | ver abajo |
| `SESSION_DB_PATH` | Path a SQLite | `/data/hvac-webapp.db` |

### Formato de USERS

```json
[
  {"username": "ruben", "password": "pass123", "name": "Ruben"},
  {"username": "mariel", "password": "pass456", "name": "Mariel"},
  {"username": "emmanuel", "password": "pass789", "name": "Emmanuel"},
  {"username": "ricardo", "password": "pass000", "name": "Ricardo"}
]
```

## Seguridad

- Login con usuario + password (bcrypt)
- JWT en cookie http-only
- Sin registro abierto
- La app solo expone chat — sin terminal, filesystem, skills, ni cron
- HTTPS provisto por NaN Cloud

## Desarrollo local

```bash
pip install -r requirements.txt
HERMES_API_URL=http://localhost:8642/v1 \
HERMES_API_KEY=tu-key \
JWT_SECRET=tu-secret \
USERS='[{"username":"test","password":"test","name":"Test"}]' \
python -m uvicorn app.main:app --port 8080
```
