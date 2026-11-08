# Invitación Sara & Alejandro — con base de datos y panel privado

## Qué incluye

- Invitación pública con el diseño original.
- Formulario RSVP conectado a una base de datos SQLite propia (`data/invitados.db`).
- Panel privado con estadísticas, búsqueda, tabla de confirmaciones y exportación CSV.
- Acceso administrativo sin botón ni enlace visible en la invitación.
- Sesión protegida con cookie HttpOnly/SameSite y límite básico de intentos de inicio de sesión.

## Requisitos

- Python 3.10 o superior.
- pip.

## Instalación en Windows

1. Descomprime la carpeta.
2. Abre una terminal dentro de esta carpeta.
3. Crea un entorno virtual:

   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```

4. Instala dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

5. Copia `.env.example` y nómbralo `.env`.
6. Abre `.env` y configura:
   - `ADMIN_USERNAME`: usuario que usarás para entrar.
   - `ADMIN_PASSWORD`: contraseña segura de al menos 12 caracteres.
   - `SESSION_SECRET`: una cadena aleatoria de al menos 32 caracteres. Puedes generarla con:

   ```powershell
   py -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

7. Inicia el servidor:

   ```powershell
   uvicorn main:app --reload
   ```

8. Abre la invitación en `http://127.0.0.1:8000`.

## Acceso al panel

No hay ningún botón de acceso administrativo en la invitación.

Abre directamente `http://127.0.0.1:8000/admin`. Si no has iniciado sesión, te enviará a la pantalla de acceso. Usa el usuario y contraseña definidos en `.env`.

## Base de datos

La base se crea automáticamente al recibir la primera confirmación y se guarda en `data/invitados.db`. Para respaldarla, detén el servidor y copia ese archivo. No compartas el archivo `.env`.

## Publicación

Para publicar en internet necesitas un servicio que ejecute FastAPI y almacenamiento persistente para SQLite. Si el hosting no garantiza disco persistente, configura `DATABASE_PATH` hacia un volumen persistente o usa PostgreSQL. En producción:
- usa HTTPS;
- configura `COOKIE_SECURE=true`;
- establece una contraseña y `SESSION_SECRET` propios;
- no subas `.env` ni `data/` a GitHub.

## API principal

- `POST /api/rsvp`: registra una confirmación pública.
- `POST /api/admin/login`: inicia sesión.
- `POST /api/admin/logout`: cierra sesión.
- `GET /api/admin/stats`: estadísticas (requiere sesión).
- `GET /api/admin/rsvps`: lista de confirmaciones (requiere sesión).
- `GET /api/admin/export.csv`: descarga CSV (requiere sesión).
