
import os
import re
import csv
import io
import time
import hmac
import sqlite3

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import create_engine, text


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

IS_VERCEL = os.getenv("VERCEL") == "1"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

DB_PATH = Path(
    os.getenv(
        "DATABASE_PATH",
        str(BASE_DIR / "data" / "invitados.db")
    )
)

if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

# En Vercel exigimos una base persistente.
if IS_VERCEL and not DATABASE_URL:
    raise RuntimeError(
        "Falta configurar DATABASE_URL en Vercel."
    )

# Compatibilidad con las URLs proporcionadas por Neon.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1
    )
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1
    )

ADMIN_USER = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SESSION_SECRET", "")

if not ADMIN_USER or len(ADMIN_PASSWORD) < 12 or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Configura ADMIN_USERNAME, ADMIN_PASSWORD "
        "(mínimo 12 caracteres) y SESSION_SECRET "
        "(mínimo 32 caracteres)."
    )


# ============================================================
# MOTOR DE BASE DE DATOS
# ============================================================

engine = None

if DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=3,
        max_overflow=2
    )


# ============================================================
# ADAPTADOR DE RESULTADOS POSTGRESQL
# ============================================================

class CompatRow(dict):

    def __iter__(self):
        return iter(self.values())


class PostgresResult:

    def __init__(self, result, lastrowid=None):
        self.result = result
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self.result.rowcount

    def fetchone(self):
        row = self.result.mappings().fetchone()

        if row is None:
            return None

        return CompatRow(row)

    def fetchall(self):
        return [
            CompatRow(row)
            for row in self.result.mappings().fetchall()
        ]


# ============================================================
# ADAPTADOR DE CONEXIÓN POSTGRESQL
# ============================================================

class PostgresConnection:

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):

        sql = sql.strip()
        params = tuple(params or ())

        is_insert = sql.upper().startswith("INSERT INTO RSVPS")

        if is_insert and "RETURNING" not in sql.upper():
            sql += " RETURNING id"

        values = {}

        def replace_placeholder(match):
            index = len(values)

            if index >= len(params):
                raise ValueError(
                    "Faltan parámetros para la consulta SQL."
                )

            values[f"p{index}"] = params[index]

            return f":p{index}"

        sql = re.sub(r"\?", replace_placeholder, sql)

        if len(values) != len(params):
            raise ValueError(
                "La cantidad de parámetros no coincide con la consulta."
            )

        result = self.connection.execute(
            text(sql),
            values
        )

        if is_insert:
            inserted_id = result.scalar_one()

            return PostgresResult(
                result,
                lastrowid=inserted_id
            )

        return PostgresResult(result)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


# ============================================================
# CREACIÓN DE TABLAS
# ============================================================

def initialize_database():

    if engine is not None:

        with engine.begin() as conn:

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rsvps (
                    id BIGSERIAL PRIMARY KEY,
                    guest TEXT NOT NULL,
                    attendance TEXT NOT NULL
                        CHECK(attendance IN (
                            'Sí, asistiré',
                            'No podré asistir'
                        )),
                    guests INTEGER NOT NULL DEFAULT 1
                        CHECK(guests BETWEEN 1 AND 5),
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """))

    else:

        DB_PATH.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        conn = sqlite3.connect(DB_PATH)

        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rsvps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guest TEXT NOT NULL,
                    attendance TEXT NOT NULL
                        CHECK(attendance IN (
                            'Sí, asistiré',
                            'No podré asistir'
                        )),
                    guests INTEGER NOT NULL DEFAULT 1
                        CHECK(guests BETWEEN 1 AND 5),
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)

            conn.commit()

        finally:
            conn.close()


# ============================================================
# CONEXIÓN AUTOMÁTICA
# ============================================================

def db():

    # PRODUCCIÓN: NEON / POSTGRESQL
    if engine is not None:

        return PostgresConnection(
            engine.connect()
        )

    # DESARROLLO LOCAL: SQLITE
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# APLICACIÓN FASTAPI
# ============================================================

app = FastAPI(
    title="Invitación Sara y Alejandro"
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="sara_admin_session",
    max_age=60 * 60 * 8,
    same_site="strict",
    https_only=os.getenv(
        "COOKIE_SECURE",
        "false"
    ).lower() == "true",
)


@app.on_event("startup")
def startup():
    initialize_database()


# ============================================================
# MODELOS DE DATOS
# ============================================================

class RSVP(BaseModel):

    guest: str = Field(
        min_length=2,
        max_length=120
    )

    attendance: str

    guests: int = Field(
        default=1,
        ge=1,
        le=5
    )

    message: str = Field(
        default="",
        max_length=1000
    )


class Login(BaseModel):

    username: str = Field(
        min_length=1,
        max_length=80
    )

    password: str = Field(
        min_length=1,
        max_length=200
    )


# ============================================================
# AUTENTICACIÓN ADMINISTRATIVA
# ============================================================

def require_admin(request: Request):

    if request.session.get("admin") != ADMIN_USER:

        raise HTTPException(
            status_code=401,
            detail="Inicia sesión para continuar."
        )

    return True


# ============================================================
# LÍMITE DE INTENTOS DE INICIO DE SESIÓN
# ============================================================

login_attempts = {}


def check_login_limit(ip):

    now = time.time()

    attempts = [
        t
        for t in login_attempts.get(ip, [])
        if now - t < 300
    ]

    login_attempts[ip] = attempts

    if len(attempts) >= 8:

        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Espera cinco minutos."
        )

    attempts.append(now)


# ============================================================
# ARCHIVOS HTML Y ESTÁTICOS
# ============================================================

@app.get("/")
def home():

    return FileResponse(
        BASE_DIR / "index.html"
    )


@app.get("/styles.css")
def invitation_styles():

    return FileResponse(
        BASE_DIR / "styles.css",
        media_type="text/css"
    )


@app.get("/script.js")
def invitation_script():

    return FileResponse(
        BASE_DIR / "script.js",
        media_type="application/javascript"
    )


@app.get("/admin.css")
def admin_styles():

    return FileResponse(
        BASE_DIR / "admin.css",
        media_type="text/css"
    )


@app.get("/admin.js")
def admin_script():

    return FileResponse(
        BASE_DIR / "admin.js",
        media_type="application/javascript"
    )


# ============================================================
# PÁGINAS ADMINISTRATIVAS
# ============================================================

@app.get("/admin")
def admin_page(request: Request):

    if request.session.get("admin") != ADMIN_USER:

        return RedirectResponse(
            "/admin/login",
            status_code=303
        )

    return FileResponse(
        BASE_DIR / "admin.html"
    )


@app.get("/admin/login")
def login_page():

    return FileResponse(
        BASE_DIR / "admin-login.html"
    )


# ============================================================
# CONFIRMACIONES DE ASISTENCIA
# ============================================================

@app.post("/api/rsvp")
def create_rsvp(payload: RSVP):

    name = re.sub(
        r"\s+",
        " ",
        payload.guest
    ).strip()

    if len(name) < 2:

        raise HTTPException(
            status_code=422,
            detail="Escribe tu nombre completo."
        )

    if payload.attendance not in (
        "Sí, asistiré",
        "No podré asistir"
    ):

        raise HTTPException(
            status_code=422,
            detail="Selecciona una respuesta válida."
        )

    conn = db()

    try:

        cur = conn.execute(
            """
            INSERT INTO rsvps
            (guest, attendance, guests, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                payload.attendance,
                payload.guests,
                payload.message.strip(),
                datetime.now(timezone.utc).isoformat()
            )
        )

        conn.commit()

        return {
            "ok": True,
            "id": cur.lastrowid,
            "message": "Tu confirmación quedó registrada. ¡Gracias!"
        }

    finally:
        conn.close()


# ============================================================
# INICIO DE SESIÓN DE LOS NOVIOS
# ============================================================

@app.post("/api/admin/login")
def admin_login(payload: Login, request: Request):

    ip = (
        request.client.host
        if request.client
        else "unknown"
    )

    check_login_limit(ip)

    user_ok = hmac.compare_digest(
        payload.username,
        ADMIN_USER
    )

    pass_ok = hmac.compare_digest(
        payload.password,
        ADMIN_PASSWORD
    )

    if not (user_ok and pass_ok):

        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos."
        )

    request.session.clear()

    request.session["admin"] = ADMIN_USER

    return {"ok": True}


# ============================================================
# CERRAR SESIÓN
# ============================================================

@app.post("/api/admin/logout")
def admin_logout(request: Request):

    request.session.clear()

    return {"ok": True}


# ============================================================
# VERIFICAR SESIÓN
# ============================================================

@app.get("/api/admin/me")
def admin_me(request: Request):

    return {
        "authenticated":
            request.session.get("admin") == ADMIN_USER
    }


# ============================================================
# ESTADÍSTICAS DEL PANEL
# ============================================================

@app.get(
    "/api/admin/stats",
    dependencies=[Depends(require_admin)]
)
def stats():

    conn = db()

    try:

        row = conn.execute("""
            SELECT
                COUNT(*) AS responses,

                SUM(
                    CASE
                        WHEN attendance = 'Sí, asistiré'
                        THEN 1 ELSE 0
                    END
                ) AS attending,

                SUM(
                    CASE
                        WHEN attendance = 'No podré asistir'
                        THEN 1 ELSE 0
                    END
                ) AS declining,

                SUM(
                    CASE
                        WHEN attendance = 'Sí, asistiré'
                        THEN guests ELSE 0
                    END
                ) AS people

            FROM rsvps
        """).fetchone()

        return {
            key: (row[key] or 0)
            for key in row.keys()
        }

    finally:
        conn.close()


# ============================================================
# LISTAR CONFIRMACIONES
# ============================================================

@app.get(
    "/api/admin/rsvps",
    dependencies=[Depends(require_admin)]
)
def list_rsvps(q: Optional[str] = None):

    conn = db()

    try:

        if q and q.strip():

            rows = conn.execute(
                """
                SELECT *
                FROM rsvps
                WHERE guest LIKE ?
                ORDER BY id DESC
                """,
                (f"%{q.strip()}%",)
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT *
                FROM rsvps
                ORDER BY id DESC
                """
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


# ============================================================
# EDITAR CONFIRMACIÓN
# ============================================================

@app.put(
    "/api/admin/rsvps/{rsvp_id}",
    dependencies=[Depends(require_admin)]
)
def update_rsvp(rsvp_id: int, payload: RSVP):

    name = re.sub(
        r"\s+",
        " ",
        payload.guest
    ).strip()

    if len(name) < 2:

        raise HTTPException(
            status_code=422,
            detail="Escribe un nombre válido."
        )

    if payload.attendance not in (
        "Sí, asistiré",
        "No podré asistir"
    ):

        raise HTTPException(
            status_code=422,
            detail="Selecciona una respuesta válida."
        )

    conn = db()

    try:

        cur = conn.execute(
            """
            UPDATE rsvps
            SET guest = ?,
                attendance = ?,
                guests = ?,
                message = ?
            WHERE id = ?
            """,
            (
                name,
                payload.attendance,
                payload.guests,
                payload.message.strip(),
                rsvp_id
            )
        )

        conn.commit()

        if cur.rowcount == 0:

            raise HTTPException(
                status_code=404,
                detail="Registro no encontrado."
            )

        return {
            "ok": True,
            "message": "Confirmación actualizada."
        }

    finally:
        conn.close()


# ============================================================
# ELIMINAR CONFIRMACIÓN
# ============================================================

@app.delete(
    "/api/admin/rsvps/{rsvp_id}",
    dependencies=[Depends(require_admin)]
)
def delete_rsvp(rsvp_id: int):

    conn = db()

    try:

        cur = conn.execute(
            "DELETE FROM rsvps WHERE id = ?",
            (rsvp_id,)
        )

        conn.commit()

        if cur.rowcount == 0:

            raise HTTPException(
                status_code=404,
                detail="Registro no encontrado."
            )

        return {"ok": True}

    finally:
        conn.close()


# ============================================================
# EXPORTAR CONFIRMACIONES A CSV
# ============================================================

@app.get(
    "/api/admin/export.csv",
    dependencies=[Depends(require_admin)]
)
def export_csv():

    conn = db()

    try:

        rows = conn.execute(
            """
            SELECT
                guest,
                attendance,
                guests,
                message,
                created_at
            FROM rsvps
            ORDER BY id DESC
            """
        ).fetchall()

        output = io.StringIO()

        writer = csv.writer(output)

        writer.writerow([
            "Nombre",
            "Asistencia",
            "Número de asistentes",
            "Mensaje",
            "Fecha de registro"
        ])

        writer.writerows([
            tuple(row)
            for row in rows
        ])

        data = "\ufeff" + output.getvalue()

        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition":
                    'attachment; filename="confirmaciones_sara_alejandro.csv"'
            }
        )

    finally:
        conn.close()
