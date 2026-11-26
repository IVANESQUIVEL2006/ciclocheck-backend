import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import mysql.connector

app = FastAPI(title="CicloCheck Pro API - Durango")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "ciclocheck_pro_db"),
        ssl_disabled=os.getenv("DB_SSL_DISABLED", "false").lower() == "true",
    )

class LoginReq(BaseModel):
    correo: str
    password: str

class RegistroReq(BaseModel):
    nombre: str
    correo: str
    password: str
    marca_bici: str
    modelo_bici: str
    tipo_bici: str
    km_iniciales: float = 0.0

class CitaReq(BaseModel):
    usuario_id: str
    nombre_cliente: str
    taller_nombre: str
    servicio: str
    fecha: str
    hora: str
    nota_adicional: str = ""

class EstadoRoboReq(BaseModel):
    vin: str
    reportada_robada: bool
    folio_reporte_robo: str | None = None

@app.get("/api/health")
def health():
    return {"status": "ok", "database": os.getenv("DB_NAME", "ciclocheck_pro_db")}

@app.post("/api/auth/login")
def login(req: LoginReq):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, nombre, correo, rol, creado_en FROM usuarios WHERE LOWER(correo)=LOWER(%s) AND password_hash=%s",
        (req.correo.strip(), req.password),
    )
    user = cur.fetchone()
    if not user:
        cur.close()
        conn.close()
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    cur.execute("SELECT * FROM bicicletas WHERE usuario_id=%s ORDER BY creado_en DESC", (user["id"],))
    bicis = cur.fetchall()
    cur.close()
    conn.close()
    return {"usuario": user, "bicicletas": bicis}

@app.post("/api/auth/register")
def register(req: RegistroReq):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM usuarios WHERE LOWER(correo)=LOWER(%s)", (req.correo.strip(),))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=409, detail="El correo ya está registrado")

    ts = int(datetime.now().timestamp() * 1000)
    user_id = f"usr_{ts}"
    bici_id = f"bici_{ts}"
    marca_code = "".join(c for c in req.marca_bici.upper() if c.isalnum()).ljust(4, "X")[:4]
    vin = f"VIN-{marca_code}-2026-DGO-{str(ts)[-4:]}"

    cur.execute(
        "INSERT INTO usuarios (id, nombre, correo, password_hash, rol) VALUES (%s, %s, %s, %s, 'ciclista')",
        (user_id, req.nombre.strip(), req.correo.strip().lower(), req.password),
    )
    cur.execute(
        """INSERT INTO bicicletas (id, usuario_id, vin, marca, modelo, tipo, km_acumulados)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (bici_id, user_id, vin, req.marca_bici.strip(), req.modelo_bici.strip(), req.tipo_bici.strip(), req.km_iniciales),
    )
    conn.commit()
    cur.close()
    conn.close()

    return {
        "usuario": {
            "id": user_id,
            "nombre": req.nombre.strip(),
            "correo": req.correo.strip().lower(),
            "rol": "ciclista",
        },
        "bicicleta": {
            "id": bici_id,
            "usuario_id": user_id,
            "vin": vin,
            "marca": req.marca_bici.strip(),
            "modelo": req.modelo_bici.strip(),
            "tipo": req.tipo_bici.strip(),
            "km_acumulados": req.km_iniciales,
            "reportada_robada": 0,
            "folio_reporte_robo": None,
        },
    }

@app.post("/api/bicicletas/estado-robo")
def actualizar_estado_robo(req: EstadoRoboReq):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    folio = req.folio_reporte_robo.strip() if (req.reportada_robada and req.folio_reporte_robo) else None
    if req.reportada_robada and not folio:
        folio = f"FGE-DGO-{str(int(datetime.now().timestamp()))[-6:]}"

    cur.execute(
        """UPDATE bicicletas
           SET reportada_robada=%s, folio_reporte_robo=%s
           WHERE UPPER(vin)=UPPER(%s)""",
        (1 if req.reportada_robada else 0, folio, req.vin.strip()),
    )
    conn.commit()
    if cur.rowcount == 0:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="VIN no encontrado")

    cur.execute("SELECT * FROM bicicletas WHERE UPPER(vin)=UPPER(%s)", (req.vin.strip(),))
    bici = cur.fetchone()
    cur.close()
    conn.close()
    return {"bicicleta": bici}

@app.post("/api/citas")
def crear_cita(req: CitaReq):
    conn = get_db()
    cur = conn.cursor()
    cita_id = f"cita_{int(datetime.now().timestamp() * 1000)}"
    cur.execute(
        """INSERT INTO citas_taller (id, usuario_id, nombre_cliente, taller_nombre, servicio, fecha, hora, nota_adicional, estado)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Recibida')""",
        (cita_id, req.usuario_id, req.nombre_cliente.strip(), req.taller_nombre.strip(), req.servicio.strip(), req.fecha.strip(), req.hora.strip(), req.nota_adicional.strip()),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"id": cita_id, "estado": "Recibida"}

@app.get("/api/admin/resumen")
def admin_resumen():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, nombre, correo, rol, creado_en FROM usuarios WHERE rol='ciclista' ORDER BY creado_en DESC")
    ciclistas = cur.fetchall()
    cur.execute("SELECT * FROM bicicletas ORDER BY creado_en DESC")
    bicicletas = cur.fetchall()
    cur.execute("SELECT * FROM citas_taller ORDER BY creado_en DESC")
    citas = cur.fetchall()
    cur.close()
    conn.close()
    return {"ciclistas": ciclistas, "bicicletas": bicicletas, "citas": citas}
