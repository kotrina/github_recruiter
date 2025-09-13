#!/usr/bin/env bash
set -e  # parar si hay error

# 1. Crear entorno virtual si no existe
if [ ! -d ".venv" ]; then
  echo ">>> Creando entorno virtual..."
  python3 -m venv .venv
fi

# 2. Activar entorno
echo ">>> Activando entorno virtual..."
source .venv/bin/activate

# 3. Instalar dependencias
echo ">>> Instalando dependencias..."
pip install -r requirements.txt

# 4. Copiar .env si no existe
if [ ! -f ".env" ]; then
  echo ">>> Creando .env desde .env.example..."
  cp .env.example .env
  echo ">>> ⚠️  Edita el archivo .env y pon tu GITHUB_TOKEN antes de seguir"
  exit 1
fi

# 5. Lanzar servidor

echo ">>> Arrancando servidor en http://localhost:8080 ..."
uvicorn main:app --reload --port 8080
