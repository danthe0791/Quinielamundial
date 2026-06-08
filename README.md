# 🏆 Quiniela Mundial 2026

Aplicación web para quiniela del Mundial 2026. Hasta 10 participantes.
Apuesta por marcador, tarjetas (Over/Under) y corners (Over/Under).

## 🚀 Deploy en Render.com (Gratis)

### 1. Subir a GitHub

```bash
# Desde la terminal en VS Code:
git init
git add .
git commit -m "Primer commit"
# Crear repo en github.com y luego:
git remote add origin https://github.com/TU_USUARIO/quiniela-mundial-2026.git
git branch -M main
git push -u origin main
```

### 2. Crear Web Service en Render

1. Ir a [render.com](https://render.com) y crear cuenta (con GitHub)
2. Click **"New +"** → **"Web Service"**
3. Conectar tu repositorio de GitHub
4. Configurar:
   - **Name**: `quiniela-mundial-2026`
   - **Region**: `Frankfurt` (Europa) o `Oregon` (US)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: **Free** ✅
5. Click **"Create Web Service"**

### 3. Mantenerlo activo 24/7 (opcional)

Render gratis "duerme" después de 15 min sin tráfico.
Para mantenerlo despierto:

1. Ir a [cron-job.org](https://cron-job.org) (gratis)
2. Crear cuenta
3. **Add Cronjob**:
   - **URL**: `https://TU-APP.onrender.com/api/live-matches`
   - **Every**: `5 minutes`
   - Guardar

Esto hará ping cada 5 minutos y Render no dormirá nunca. ✅

### 4. Compartir

Render te dará una URL como:
`https://quiniela-mundial-2026.onrender.com`

El **primer usuario** en registrarse será **admin** automáticamente.

### ⚠️ Notas importantes

- Los datos se almacenan en **SQLite** (archivo local). Si Render reinicia
  el servicio, los datos se pierden. Para uso real, considera hacer
  backups periódicos descargando la base de datos.
- El **auto-sync** con OpenLigaDB ocurre cada 5 minutos automáticamente.
- El frontend se actualiza solo cada 30 segundos.
