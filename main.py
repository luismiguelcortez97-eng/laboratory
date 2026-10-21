
"""LC Lab Web - Sistema de Laboratorio Clinico"""

import os
import json
from pathlib import Path
from datetime import date, timedelta

from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from starlette.middleware.sessions import SessionMiddleware

from database import db, DOCS_DIR, verify_password, hash_password
from helpers import (
    now_iso, today_str, format_money, safe_float, safe_int,
    format_dt, calcular_margen, METODOS_PAGO, ESTADOS_PAGO, SEXOS, PUESTOS, ahora_local
)
from pdf_gen import generar_pdf_venta, generar_pdf_milab, generar_pdf_reporte_lc

BASE = Path(__file__).resolve().parent

app = FastAPI(title="LC Lab", version="2.0.0")


@app.get("/health")
async def health_check():
    try:
        resultado = db.fetchone("SELECT 1 AS conexion")

        if resultado and resultado["conexion"] == 1:
            return {
                "status": "ok",
                "database": (
                    "postgresql"
                    if db.use_postgres
                    else "sqlite"
                ),
                "connection": "successful"
            }

        return {
            "status": "error",
            "connection": "unexpected_result"
        }

    except Exception:
        return {
            "status": "error",
            "connection": "failed"
        }

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get(
        "SESSION_SECRET",
        "lc-lab-session-change-this"
    )
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE / "static")),
    name="static"
)

_env = Environment(loader=FileSystemLoader(str(BASE / "templates")), autoescape=True, cache_size=100)
_env.filters["money"] = format_money
_env.filters["dt"] = format_dt
templates = Jinja2Templates(env=_env)

# Guarda el conjunto exacto de operaciones que se confirmó desde Registro Diario.
db.execute("""CREATE TABLE IF NOT EXISTS cierres_diarios (
    sucursal_id INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    venta_ids TEXT NOT NULL DEFAULT '',
    confirmado_por INTEGER,
    confirmado_en TEXT NOT NULL,
    PRIMARY KEY (sucursal_id, fecha)
)""")

# Añadir la columna una sola vez. Solo en esa primera migración se recuperan
# las ventas que ya estaban confirmadas en cierres históricos.
try:
    columnas_ventas = db.fetchall("PRAGMA table_info(ventas)") if not db.use_postgres else db.fetchall(
        "SELECT column_name AS name FROM information_schema.columns WHERE table_name='ventas'"
    )
    existe_confirmado = any(col["name"] == "confirmado" for col in columnas_ventas)
except Exception:
    existe_confirmado = False

if not existe_confirmado:
    db.execute("ALTER TABLE ventas ADD COLUMN confirmado INTEGER NOT NULL DEFAULT 0")
    try:
        cierres_anteriores = db.fetchall("SELECT venta_ids FROM cierres_diarios")
        for cierre_anterior in cierres_anteriores:
            for id_texto in (cierre_anterior["venta_ids"] or "").split(","):
                if id_texto.strip().isdigit():
                    db.execute("UPDATE ventas SET confirmado=1 WHERE id=?", (int(id_texto),))
    except Exception:
        pass

# Migración de descuentos para bases existentes (SQLite y PostgreSQL).
try:
    columnas_descuento = db.fetchall("PRAGMA table_info(ventas)") if not db.use_postgres else db.fetchall(
        "SELECT column_name AS name FROM information_schema.columns WHERE table_name='ventas'"
    )
    nombres_columnas_descuento = {col["name"] for col in columnas_descuento}
except Exception:
    nombres_columnas_descuento = set()

if "descuento_porcentaje" not in nombres_columnas_descuento:
    try:
        db.execute("ALTER TABLE ventas ADD COLUMN descuento_porcentaje REAL NOT NULL DEFAULT 0")
    except Exception:
        pass
if "descuento_monto" not in nombres_columnas_descuento:
    try:
        db.execute("ALTER TABLE ventas ADD COLUMN descuento_monto REAL NOT NULL DEFAULT 0")
    except Exception:
        pass


def get_user(request: Request):
    uid = request.session.get("user_id")
    return db.fetchone("SELECT * FROM usuarios WHERE id=? AND activo=1", (uid,)) if uid else None

def flash(request, msg, cat="success"):
    request.session.setdefault("flashes", []).append({"msg": msg, "cat": cat})

def get_flashes(request):
    return request.session.pop("flashes", [])


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})

@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    user = db.fetchone("SELECT * FROM usuarios WHERE username=? AND activo=1", (username.strip(),))
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(request, "login.html", {"error": "Usuario o contrasena incorrectos"})
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    hoy = today_str()
    rows = db.fetchall(
        """SELECT v.total, v.monto_recibido, v.estado_pago, v.confirmado, s.nombre as suc FROM ventas v
           JOIN sucursales s ON s.id=v.sucursal_id
           WHERE date(v.fecha_hora)=? AND COALESCE(v.activo, 0)=1 AND COALESCE(v.confirmado, 0)=1 AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN ('COTIZACION', 'CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')""", (hoy,))
    total_ventas = sum(r["total"] or 0 for r in rows)
    total_cobrado = sum(r["monto_recibido"] or 0 for r in rows)
    total_pend = sum(max(0, (r["total"] or 0) - (r["monto_recibido"] or 0)) for r in rows)
    por_suc = {}
    for r in rows:
        por_suc[r["suc"]] = por_suc.get(r["suc"], 0) + (r["total"] or 0)
    pac = db.fetchone("SELECT COUNT(*) as c FROM pacientes WHERE date(fecha_registro)=? AND activo=1", (hoy,))
    top = db.fetchall(
        """SELECT vd.nombre, SUM(vd.cantidad) as cant FROM venta_detalles vd
           JOIN ventas v ON v.id=vd.venta_id WHERE date(v.fecha_hora)=? AND COALESCE(v.activo, 0)=1 AND COALESCE(v.confirmado, 0)=1 AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN ('COTIZACION', 'CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')
           GROUP BY vd.nombre ORDER BY cant DESC LIMIT 8""", (hoy,))
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "flashes": get_flashes(request),
        "total_ventas": total_ventas, "total_cobrado": total_cobrado, "total_pend": total_pend,
        "pacientes_hoy": pac["c"] if pac else 0, "por_suc": por_suc, "top_estudios": top, "hoy": hoy,
    })

@app.get("/pacientes", response_class=HTMLResponse)
async def pacientes_list(request: Request, q: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if q:
        rows = db.fetchall(
            """SELECT p.*, s.nombre as sucursal FROM pacientes p JOIN sucursales s ON s.id=p.sucursal_id
               WHERE p.activo=1 AND (p.nombre_completo LIKE ? OR p.folio LIKE ? OR p.telefono LIKE ?)
               ORDER BY p.fecha_registro DESC LIMIT 150""", (f"%{q}%", f"%{q}%", f"%{q}%"))
    else:
        rows = db.fetchall(
            """SELECT p.*, s.nombre as sucursal FROM pacientes p JOIN sucursales s ON s.id=p.sucursal_id
               WHERE p.activo=1 ORDER BY p.fecha_registro DESC LIMIT 100""")
    return templates.TemplateResponse(request, "pacientes.html", {"user": user, "flashes": get_flashes(request),
        "pacientes": rows, "sucursales": db.fetchall("SELECT * FROM sucursales WHERE activa=1"),
        "empleados": db.fetchall("SELECT * FROM empleados WHERE activo=1"), "sexos": SEXOS, "q": q,
    })

@app.get("/api/pacientes/buscar")
async def api_buscar_pacientes(request: Request, q: str = ""):
    user = get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    termino = q.strip()
    if len(termino) < 1:
        return []
    filas = db.fetchall(
        """SELECT p.id, p.folio, p.nombre_completo, p.edad, p.sexo, p.telefono,
                  p.fecha_nacimiento, s.nombre AS sucursal
           FROM pacientes p
           LEFT JOIN sucursales s ON s.id=p.sucursal_id
           WHERE p.activo=1
             AND (p.nombre_completo LIKE ? OR p.folio LIKE ? OR p.telefono LIKE ?)
           ORDER BY p.nombre_completo
           LIMIT 40""",
        (f"%{termino}%", f"%{termino}%", f"%{termino}%")
    )
    return [dict(fila) for fila in filas]


@app.get("/api/pacientes/{paciente_id}")
async def api_datos_paciente(paciente_id: int, request: Request):
    user = get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autorizado")
    paciente = db.fetchone(
        """SELECT p.*, s.nombre AS sucursal, e.nombre_completo AS empleado_registro
           FROM pacientes p
           LEFT JOIN sucursales s ON s.id=p.sucursal_id
           LEFT JOIN empleados e ON e.id=p.empleado_id
           WHERE p.id=? AND p.activo=1""",
        (paciente_id,)
    )
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return dict(paciente)


@app.post("/pacientes/guardar")
async def pacientes_guardar(request: Request, nombre_completo: str = Form(...), sucursal_id: int = Form(...),
    empleado_id: int = Form(...), edad: str = Form(""), sexo: str = Form(""), fecha_nacimiento: str = Form(""),
    telefono: str = Form(""), fecha_entrega: str = Form(""), modalidad: str = Form(""),
    observaciones: str = Form(""), paciente_id: str = Form("")):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not nombre_completo.strip():
        flash(request, "El nombre es obligatorio", "danger")
        return RedirectResponse("/pacientes", status_code=303)
    folio = db.generar_folio("P")
    db.execute(
        """INSERT INTO pacientes (folio, nombre_completo, edad, sexo, fecha_nacimiento, telefono,
           sucursal_id, empleado_id, fecha_registro, fecha_entrega_resultados, modalidad_entrega,
           observaciones, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (folio, nombre_completo.strip(), safe_int(edad) if edad else None, sexo or None,
         fecha_nacimiento or None, telefono or None, sucursal_id, empleado_id, now_iso(),
         fecha_entrega or None, modalidad or None, observaciones or None, now_iso()))
    flash(request, f"Paciente registrado. Folio: {folio}")
    return RedirectResponse("/pacientes", status_code=303)

@app.get("/cotizacion", response_class=HTMLResponse)
async def cotizacion_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "cotizacion.html", {"user": user, "flashes": get_flashes(request),
        "pacientes": db.fetchall("SELECT id, folio, nombre_completo FROM pacientes WHERE activo=1 ORDER BY fecha_registro DESC LIMIT 300"),
        "sucursales": db.fetchall("SELECT * FROM sucursales WHERE activa=1"),
        "empleados": db.fetchall("SELECT * FROM empleados WHERE activo=1"), "metodos": METODOS_PAGO,
    })

@app.get("/api/estudios/{sucursal_id}")
async def api_estudios(sucursal_id: int, request: Request):
    if not get_user(request):
        raise HTTPException(401)
    rows = db.fetchall("SELECT id, clave, nombre, precio_venta, costo_insumo FROM estudios WHERE sucursal_id=? AND activo=1 ORDER BY nombre", (sucursal_id,))
    return [dict(r) for r in rows]

@app.post("/cotizacion/guardar")
async def cotizacion_guardar(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    paciente_id = safe_int(form.get("paciente_id"))
    sucursal_id = safe_int(form.get("sucursal_id"))
    empleado_id = safe_int(form.get("empleado_id"))
    metodo = form.get("metodo_pago") or "Efectivo"
    estado_deseado = form.get("estado") or "PENDIENTE"
    monto = safe_float(form.get("monto_recibido"))
    descuento_porcentaje = max(0.0, min(100.0, safe_float(form.get("descuento_porcentaje"))))
    est_ids = form.getlist("estudio_id")
    cants = form.getlist("cantidad")
    precios = form.getlist("precio")
    if not paciente_id or not sucursal_id or not est_ids:
        flash(request, "Faltan datos", "danger")
        return RedirectResponse("/cotizacion", status_code=303)
    partidas, total = [], 0.0
    for i, eid in enumerate(est_ids):
        est = db.fetchone("SELECT * FROM estudios WHERE id=?", (int(eid),))
        if not est:
            continue
        cant = safe_float(cants[i] if i < len(cants) else 1, 1)
        precio = safe_float(precios[i] if i < len(precios) else est["precio_venta"])
        importe = round(cant * precio, 2)
        partidas.append({"estudio_id": est["id"], "clave": est["clave"], "nombre": est["nombre"],
            "cantidad": cant, "precio_unitario": precio, "costo_unitario": float(est["costo_insumo"] or 0), "importe": importe})
        total += importe
    if not partidas:
        flash(request, "Sin estudios", "danger")
        return RedirectResponse("/cotizacion", status_code=303)
    subtotal = round(total, 2)
    descuento_monto = round(subtotal * descuento_porcentaje / 100.0, 2)
    total = round(max(0.0, subtotal - descuento_monto), 2)
    if estado_deseado == "COTIZACION":
        estado, monto = "COTIZACION", 0.0
    elif estado_deseado == "PENDIENTE":
        estado, monto = "PENDIENTE", 0.0
    elif estado_deseado == "PAGADO":
        estado, monto = "PAGADO", total
    elif monto >= total - 0.01:
        estado = "PAGADO"
        monto = monto if monto > 0 else total
    else:
        estado = "PARCIAL" if monto > 0 else "PENDIENTE"
    saldo = max(0, total - monto)
    folio = db.generar_folio("V")
    with db.cursor() as cur:
        cur.execute("""INSERT INTO ventas (folio, paciente_id, sucursal_id, empleado_id, fecha_hora, total,
            estado_pago, metodo_pago, monto_recibido, saldo_pendiente, descuento_porcentaje, descuento_monto, observaciones, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (folio, paciente_id, sucursal_id, empleado_id, now_iso(), total, estado, metodo if monto > 0 else None,
             monto, saldo, descuento_porcentaje, descuento_monto, (form.get("observaciones") or "").strip() or None, now_iso()))
        venta_id = cur.lastrowid
        for p in partidas:
            cur.execute("""INSERT INTO venta_detalles (venta_id, estudio_id, clave, nombre, cantidad, precio_unitario, costo_unitario, importe)
                VALUES (?,?,?,?,?,?,?,?)""", (venta_id, p["estudio_id"], p["clave"], p["nombre"], p["cantidad"], p["precio_unitario"], p["costo_unitario"], p["importe"]))
        if monto > 0:
            cur.execute("INSERT INTO pagos (venta_id, monto, metodo_pago, fecha_hora, empleado_id) VALUES (?,?,?,?,?)",
                (venta_id, monto, metodo, now_iso(), empleado_id))
    try:
        venta = db.fetchone("SELECT * FROM ventas WHERE id=?", (venta_id,))
        pac = db.fetchone("SELECT * FROM pacientes WHERE id=?", (paciente_id,))
        suc = db.fetchone("SELECT nombre FROM sucursales WHERE id=?", (sucursal_id,))
        emp = db.fetchone("SELECT nombre_completo FROM empleados WHERE id=?", (empleado_id,))
        pdf_path = generar_pdf_venta(dict(venta), partidas, dict(pac), suc["nombre"], emp["nombre_completo"] if emp else "", observaciones=(form.get("observaciones") or "").strip())
        db.execute("UPDATE ventas SET pdf_path=? WHERE id=?", (pdf_path, venta_id))
    except Exception as e:
        print("PDF:", e)
    flash(request, f"Venta {folio} guardada — {estado}")
    return RedirectResponse(f"/diario?sucursal_id={sucursal_id}", status_code=303)

@app.get("/diario", response_class=HTMLResponse)
async def diario(request: Request, sucursal_id: int = 0, fecha: str = "", q: str = "", estado: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    sucursales = db.fetchall("SELECT * FROM sucursales WHERE activa=1")
    if not sucursal_id and sucursales:
        sucursal_id = sucursales[0]["id"]
    fecha = fecha or today_str()
    sql = """SELECT v.*, p.nombre_completo as paciente, p.edad, e.nombre_completo as empleado,
        (SELECT GROUP_CONCAT(vd.nombre, ', ') FROM venta_detalles vd WHERE vd.venta_id=v.id) as estudios
        FROM ventas v JOIN pacientes p ON p.id=v.paciente_id LEFT JOIN empleados e ON e.id=v.empleado_id
        WHERE v.sucursal_id=? AND date(v.fecha_hora)=? AND COALESCE(v.activo, 0)=1 AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN ('CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')"""
    params = [sucursal_id, fecha]
    if estado and estado != "Todos":
        sql += " AND v.estado_pago=?"; params.append(estado)
    if q:
        sql += " AND (p.nombre_completo LIKE ? OR v.folio LIKE ?)"; params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY v.fecha_hora"
    rows = db.fetchall(sql, params)
    total_ventas = sum(r["total"] or 0 for r in rows if r["confirmado"] and r["estado_pago"] not in ("CANCELADO", "COTIZACION"))
    total_cobrado = sum(r["monto_recibido"] or 0 for r in rows if r["confirmado"] and r["estado_pago"] not in ("CANCELADO", "COTIZACION"))
    total_pend = sum(max(0, (r["total"] or 0) - (r["monto_recibido"] or 0)) for r in rows if r["confirmado"] and r["estado_pago"] not in ("CANCELADO", "COTIZACION"))
    por_met = {}
    for r in rows:
        if r["confirmado"] and r["estado_pago"] not in ("CANCELADO", "COTIZACION"):
            m = r["metodo_pago"] or "Sin metodo"
            por_met[m] = por_met.get(m, 0) + (r["monto_recibido"] or 0)
    suc_nombre = next((s["nombre"] for s in sucursales if s["id"] == sucursal_id), "")
    return templates.TemplateResponse(request, "diario.html", {"user": user, "flashes": get_flashes(request),
        "operaciones": rows, "sucursales": sucursales, "sucursal_id": sucursal_id,
        "suc_nombre": suc_nombre, "fecha": fecha, "q": q, "estado": estado or "Todos",
        "cierre_diario": db.fetchone("SELECT confirmado_en, confirmado_por, venta_ids FROM cierres_diarios WHERE sucursal_id=? AND fecha=?", (sucursal_id, fecha)),
        "estados": ["Todos"] + ESTADOS_PAGO, "total_ventas": total_ventas,
        "total_cobrado": total_cobrado, "total_pend": total_pend, "por_met": por_met, "num_ops": len(rows),
    })

@app.post("/diario/confirmar-venta")
async def confirmar_venta_individual(
    request: Request,
    venta_id: int = Form(...),
    sucursal_id: int = Form(...),
    fecha: str = Form("")
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    venta = db.fetchone(
        """SELECT id, estado_pago, activo FROM ventas
           WHERE id=? AND sucursal_id=?""",
        (venta_id, sucursal_id)
    )
    if not venta or not venta["activo"]:
        flash(request, "No se encontró una operación activa para confirmar.", "danger")
    elif (venta["estado_pago"] or "").upper() in ("COTIZACION", "CANCELADO", "CANCELADA", "CANCELLED", "ANULADO", "ANULADA"):
        flash(request, "Las cotizaciones y operaciones canceladas no se pueden confirmar para reportes.", "danger")
    else:
        db.execute(
            "UPDATE ventas SET confirmado=1, updated_at=? WHERE id=? AND sucursal_id=? AND activo=1",
            (now_iso(), venta_id, sucursal_id)
        )
        flash(request, "Paciente confirmado. Ya se incluirá en los reportes correspondientes.")
    destino = f"/diario?sucursal_id={sucursal_id}"
    if fecha:
        destino += f"&fecha={fecha}"
    return RedirectResponse(destino, status_code=303)


@app.post("/diario/reiniciar-hoy")
async def reiniciar_registro_hoy(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede reiniciar el registro de hoy.")
    hoy = today_str()
    db.execute(
        """UPDATE ventas SET activo=0, confirmado=0, estado_pago='CANCELADO', updated_at=?
           WHERE date(fecha_hora)=? AND COALESCE(activo, 0)=1""",
        (now_iso(), hoy)
    )
    db.execute("DELETE FROM cierres_diarios WHERE fecha=?", (hoy,))
    flash(request, f"Registro diario de hoy ({hoy}) reiniciado. El historial de otros días se conservó.")
    return RedirectResponse(f"/diario?fecha={hoy}", status_code=303)


@app.post("/diario/pago")
async def registrar_pago(request: Request, venta_id: int = Form(...), monto: float = Form(...), metodo_pago: str = Form("Efectivo")):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    venta = db.fetchone("SELECT * FROM ventas WHERE id=?", (venta_id,))
    if not venta:
        flash(request, "No encontrada", "danger")
        return RedirectResponse("/diario", status_code=303)
    nuevo = (venta["monto_recibido"] or 0) + monto
    saldo = max(0, (venta["total"] or 0) - nuevo)
    estado = "PAGADO" if saldo < 0.01 else "PARCIAL"
    db.execute("UPDATE ventas SET monto_recibido=?, saldo_pendiente=?, estado_pago=?, metodo_pago=?, updated_at=? WHERE id=?",
        (nuevo, saldo, estado, metodo_pago, now_iso(), venta_id))
    db.execute("INSERT INTO pagos (venta_id, monto, metodo_pago, fecha_hora, empleado_id) VALUES (?,?,?,?,?)",
        (venta_id, monto, metodo_pago, now_iso(), user["empleado_id"]))
    flash(request, f"Pago registrado. Estado: {estado}")
    return RedirectResponse(f"/diario?sucursal_id={venta['sucursal_id']}", status_code=303)


@app.post("/diario/eliminar")
async def eliminar_operacion(
    request: Request,
    venta_id: int = Form(...),
    sucursal_id: int = Form(...),
    fecha: str = Form("")
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    venta = db.fetchone(
        "SELECT id, activo FROM ventas WHERE id=? AND sucursal_id=?",
        (venta_id, sucursal_id)
    )

    if not venta or not venta["activo"]:
        flash(request, "La operación no existe o ya fue retirada.", "danger")
    else:
        db.execute(
            """UPDATE ventas
               SET activo=0, estado_pago='CANCELADO', updated_at=?
               WHERE id=? AND sucursal_id=? AND activo=1""",
            (now_iso(), venta_id, sucursal_id)
        )

        flash(
            request,
            "Operación retirada del Registro diario. Se conservó el historial.",
            "success"
        )

    destino = f"/diario?sucursal_id={sucursal_id}"
    if fecha:
        destino += f"&fecha={fecha}"

    return RedirectResponse(destino, status_code=303)


@app.post("/diario/confirmar")
async def confirmar_registro_diario(
    request: Request,
    sucursal_id: int = Form(...),
    fecha: str = Form(...),
    q: str = Form(""),
    estado: str = Form("Todos")
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Debe coincidir con las operaciones visibles en Registro Diario, incluidos filtros.
    sql = """SELECT v.id
             FROM ventas v
             JOIN pacientes p ON p.id=v.paciente_id
             WHERE v.sucursal_id=? AND date(v.fecha_hora)=?
               AND COALESCE(v.activo, 0)=1
               AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN
                   ('CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')"""
    params = [sucursal_id, fecha]
    if estado and estado != "Todos":
        sql += " AND v.estado_pago=?"
        params.append(estado)
    if q:
        sql += " AND (p.nombre_completo LIKE ? OR v.folio LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY v.fecha_hora, v.id"
    ids = [str(row["id"]) for row in db.fetchall(sql, params)]
    ids_guardados = ",".join(ids)

    # La confirmación general del día también marca cada operación como confirmada,
    # para que los reportes nuevos basados en la marca individual sigan funcionando.
    for id_confirmado in ids:
        db.execute(
            "UPDATE ventas SET confirmado=1, updated_at=? WHERE id=? AND sucursal_id=? AND COALESCE(activo, 0)=1",
            (now_iso(), int(id_confirmado), sucursal_id)
        )

    existente = db.fetchone(
        "SELECT venta_ids FROM cierres_diarios WHERE sucursal_id=? AND fecha=?",
        (sucursal_id, fecha)
    )
    if existente and existente["venta_ids"] == ids_guardados:
        flash(request, f"Registro del {fecha} ya confirmado; no cambió la lista de operaciones.")
    else:
        db.execute(
            """INSERT INTO cierres_diarios (sucursal_id, fecha, venta_ids, confirmado_por, confirmado_en)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(sucursal_id, fecha) DO UPDATE SET
                 venta_ids=excluded.venta_ids,
                 confirmado_por=excluded.confirmado_por,
                 confirmado_en=excluded.confirmado_en""",
            (sucursal_id, fecha, ids_guardados, user["id"], now_iso())
        )
        flash(request, f"Registro diario confirmado: {len(ids)} operaciones guardadas para reportes.")
    destino = f"/diario?sucursal_id={sucursal_id}&fecha={fecha}"
    if estado and estado != "Todos":
        destino += f"&estado={estado}"
    if q:
        from urllib.parse import quote
        destino += f"&q={quote(q)}"
    return RedirectResponse(destino, status_code=303)


@app.get("/catalogo", response_class=HTMLResponse)
async def catalogo(request: Request, sucursal_id: int = 0):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    sucursales = db.fetchall("SELECT * FROM sucursales WHERE activa=1")
    if not sucursal_id and sucursales:
        sucursal_id = sucursales[0]["id"]
    estudios = db.fetchall("SELECT * FROM estudios WHERE sucursal_id=? ORDER BY nombre", (sucursal_id,)) if sucursal_id else []
    return templates.TemplateResponse(request, "catalogo.html", {"user": user, "flashes": get_flashes(request),
        "estudios": estudios, "sucursales": sucursales, "sucursal_id": sucursal_id,
    })

@app.get("/catalogo/respaldo.json")
async def catalogo_respaldo(request: Request, sucursal_id: int = 0):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    suc = db.fetchone("SELECT id, nombre FROM sucursales WHERE id=? AND activa=1", (sucursal_id,)) if sucursal_id else None
    if not suc:
        suc = db.fetchone("SELECT id, nombre FROM sucursales WHERE activa=1 ORDER BY id LIMIT 1")
    if not suc:
        raise HTTPException(status_code=404, detail="No hay sucursales activas.")
    estudios = db.fetchall(
        "SELECT clave, nombre, precio_venta, costo_insumo, activo FROM estudios WHERE sucursal_id=? ORDER BY nombre",
        (suc["id"],)
    )
    respaldo = {
        "formato": "lc-lab-catalogo",
        "version": 1,
        "sucursal": suc["nombre"],
        "exportado_en": now_iso(),
        "estudios": [dict(e) for e in estudios],
    }
    return JSONResponse(
        content=respaldo,
        headers={"Content-Disposition": 'attachment; filename="respaldo_catalogo_laboratory.json"'}
    )


@app.post("/catalogo/restaurar")
async def catalogo_restaurar(
    request: Request,
    sucursal_id: int = Form(...),
    archivo: UploadFile = File(...)
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede restaurar el catálogo.")
    if not archivo.filename or not archivo.filename.lower().endswith(".json"):
        flash(request, "Selecciona un archivo de respaldo .json válido.", "danger")
        return RedirectResponse(f"/catalogo?sucursal_id={sucursal_id}", status_code=303)
    try:
        contenido = await archivo.read()
        if len(contenido) > 5 * 1024 * 1024:
            raise ValueError("El archivo supera el límite de 5 MB.")
        respaldo = json.loads(contenido.decode("utf-8-sig"))
        if respaldo.get("formato") != "lc-lab-catalogo" or not isinstance(respaldo.get("estudios"), list):
            raise ValueError("El archivo no corresponde a un respaldo de catálogo LC Lab.")
        estudios = respaldo["estudios"]
        if len(estudios) > 10000:
            raise ValueError("El respaldo contiene demasiados registros.")
        for e in estudios:
            if not isinstance(e, dict) or not str(e.get("clave", "")).strip() or not str(e.get("nombre", "")).strip():
                raise ValueError("Hay estudios sin clave o nombre.")
            precio = safe_float(e.get("precio_venta"))
            costo = safe_float(e.get("costo_insumo"))
            if precio < 0 or costo < 0:
                raise ValueError("Los precios y costos no pueden ser negativos.")
        suc = db.fetchone("SELECT id FROM sucursales WHERE id=? AND activa=1", (sucursal_id,))
        if not suc:
            raise ValueError("La sucursal seleccionada no existe o está inactiva.")
        agregados = actualizados = 0
        for e in estudios:
            clave = str(e["clave"]).strip()
            nombre = str(e["nombre"]).strip()
            precio = safe_float(e.get("precio_venta"))
            costo = safe_float(e.get("costo_insumo"))
            activo = 1 if safe_int(e.get("activo"), 1) else 0
            existente = db.fetchone(
                "SELECT id FROM estudios WHERE sucursal_id=? AND clave=?",
                (sucursal_id, clave)
            )
            if existente:
                db.execute(
                    "UPDATE estudios SET nombre=?, precio_venta=?, costo_insumo=?, activo=?, updated_at=? WHERE id=?",
                    (nombre, precio, costo, activo, now_iso(), existente["id"])
                )
                actualizados += 1
            else:
                db.execute(
                    "INSERT INTO estudios (clave, nombre, precio_venta, costo_insumo, activo, sucursal_id, created_at) VALUES (?,?,?,?,?,?,?)",
                    (clave, nombre, precio, costo, activo, sucursal_id, now_iso())
                )
                agregados += 1
        flash(request, f"Respaldo restaurado: {agregados} estudios agregados y {actualizados} actualizados. No se eliminaron otros estudios.")
    except Exception as e:
        flash(request, f"No se pudo restaurar el respaldo: {e}", "danger")
    finally:
        await archivo.close()
    return RedirectResponse(f"/catalogo?sucursal_id={sucursal_id}", status_code=303)


@app.post("/catalogo/guardar")
async def catalogo_guardar(request: Request, sucursal_id: int = Form(...), clave: str = Form(...),
    nombre: str = Form(...), precio_venta: float = Form(0), costo_insumo: float = Form(0), estudio_id: str = Form("")):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        if estudio_id:
            db.execute("UPDATE estudios SET clave=?, nombre=?, precio_venta=?, costo_insumo=?, updated_at=? WHERE id=?",
                (clave.strip(), nombre.strip(), precio_venta, costo_insumo, now_iso(), int(estudio_id)))
            flash(request, "Estudio actualizado")
        else:
            db.execute("INSERT INTO estudios (clave, nombre, precio_venta, costo_insumo, activo, sucursal_id, created_at) VALUES (?,?,?,?,1,?,?)",
                (clave.strip(), nombre.strip(), precio_venta, costo_insumo, sucursal_id, now_iso()))
            flash(request, "Estudio agregado")
    except Exception as e:
        flash(request, "Clave duplicada" if "UNIQUE" in str(e) else str(e), "danger")
    return RedirectResponse(f"/catalogo?sucursal_id={sucursal_id}", status_code=303)

@app.post("/catalogo/toggle")
async def catalogo_toggle(request: Request, estudio_id: int = Form(...), sucursal_id: int = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    est = db.fetchone("SELECT activo FROM estudios WHERE id=?", (estudio_id,))
    if est:
        db.execute("UPDATE estudios SET activo=?, updated_at=? WHERE id=?", (0 if est["activo"] else 1, now_iso(), estudio_id))
    return RedirectResponse(f"/catalogo?sucursal_id={sucursal_id}", status_code=303)

@app.get("/empleados", response_class=HTMLResponse)
async def empleados_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede administrar empleados y usuarios.")
    empleados = db.fetchall(
        """SELECT e.*, u.id AS usuario_id, u.username AS username,
                  u.rol AS rol_usuario, u.activo AS usuario_activo
           FROM empleados e
           LEFT JOIN usuarios u ON u.empleado_id=e.id
           ORDER BY e.nombre_completo"""
    )
    return templates.TemplateResponse(request, "empleados.html", {
        "user": user, "flashes": get_flashes(request),
        "empleados": empleados, "puestos": PUESTOS,
    })


@app.post("/empleados/guardar")
async def empleados_guardar(
    request: Request,
    nombre_completo: str = Form(...),
    puesto: str = Form(...),
    empleado_id: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    rol_usuario: str = Form("Recepcionista"),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede crear o modificar empleados y usuarios.")

    nombre = nombre_completo.strip()
    username = username.strip().lower()
    rol_usuario = rol_usuario.strip()
    if not nombre:
        flash(request, "El nombre completo es obligatorio.", "danger")
        return RedirectResponse("/empleados", status_code=303)
    if rol_usuario not in ("Administrador", "Recepcionista"):
        flash(request, "Nivel de acceso no válido.", "danger")
        return RedirectResponse("/empleados", status_code=303)

    if empleado_id:
        emp = db.fetchone("SELECT id FROM empleados WHERE id=?", (int(empleado_id),))
        if not emp:
            flash(request, "No se encontró el empleado.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        cuenta = db.fetchone("SELECT id, username FROM usuarios WHERE empleado_id=?", (int(empleado_id),))
        if not username:
            flash(request, "El nombre de usuario es obligatorio.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        if not cuenta and not password:
            flash(request, "Escribe una contraseña para crear el acceso de este empleado.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        if password and len(password) < 6:
            flash(request, "La contraseña debe tener al menos 6 caracteres.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        otro = db.fetchone("SELECT id FROM usuarios WHERE username=? AND empleado_id IS NOT NULL AND empleado_id<>?", (username, int(empleado_id)))
        if otro:
            flash(request, "Ese nombre de usuario ya está ocupado.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        db.execute("UPDATE empleados SET nombre_completo=?, puesto=?, updated_at=? WHERE id=?",
                   (nombre, puesto, now_iso(), int(empleado_id)))
        if cuenta:
            if password:
                db.execute("UPDATE usuarios SET username=?, password_hash=?, nombre_completo=?, rol=? WHERE id=?",
                           (username, hash_password(password), nombre, rol_usuario, cuenta["id"]))
            else:
                db.execute("UPDATE usuarios SET username=?, nombre_completo=?, rol=? WHERE id=?",
                           (username, nombre, rol_usuario, cuenta["id"]))
        else:
            db.execute("""INSERT INTO usuarios
                (username, password_hash, nombre_completo, rol, empleado_id, activo, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (username, hash_password(password), nombre, rol_usuario, int(empleado_id), now_iso()))
        flash(request, "Empleado y acceso actualizados.")
    else:
        if not username or len(username) < 3:
            flash(request, "El usuario debe tener al menos 3 caracteres.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        if len(password) < 6:
            flash(request, "La contraseña debe tener al menos 6 caracteres.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        if db.fetchone("SELECT id FROM usuarios WHERE username=?", (username,)):
            flash(request, "Ese nombre de usuario ya existe.", "danger")
            return RedirectResponse("/empleados", status_code=303)
        with db.cursor() as cur:
            cur.execute("""INSERT INTO empleados
                (nombre_completo, puesto, activo, fecha_alta, created_at)
                VALUES (?, ?, 1, ?, ?)""", (nombre, puesto, today_str(), now_iso()))
            nuevo_id = cur.lastrowid
            cur.execute("""INSERT INTO usuarios
                (username, password_hash, nombre_completo, rol, empleado_id, activo, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (username, hash_password(password), nombre, rol_usuario, nuevo_id, now_iso()))
        flash(request, "Empleado creado con su usuario de acceso.")
    return RedirectResponse("/empleados", status_code=303)


@app.post("/empleados/toggle")
async def empleados_toggle(request: Request, empleado_id: int = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede activar o desactivar empleados.")
    emp = db.fetchone("SELECT activo FROM empleados WHERE id=?", (empleado_id,))
    if emp:
        nuevo_estado = 0 if emp["activo"] else 1
        db.execute("UPDATE empleados SET activo=?, updated_at=? WHERE id=?", (nuevo_estado, now_iso(), empleado_id))
        db.execute("UPDATE usuarios SET activo=? WHERE empleado_id=?", (nuevo_estado, empleado_id))
    return RedirectResponse("/empleados", status_code=303)

@app.get("/reportes", response_class=HTMLResponse)
async def reportes_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "reportes.html", {"user": user, "flashes": get_flashes(request),
        "sucursales": db.fetchall("SELECT * FROM sucursales WHERE activa=1"), "resultado": None,
    })

@app.post("/reportes/generar")
async def reportes_generar(request: Request, sucursal_id: int = Form(...), tipo: str = Form(...),
    desde: str = Form(...), hasta: str = Form(...), codigo: str = Form(...),
    confirmar_pdf: str = Form("0")):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    sucursales = db.fetchall("SELECT * FROM sucursales WHERE activa=1")
    datos_form = {
        "user": user, "flashes": get_flashes(request), "sucursales": sucursales,
        "resultado": None, "revision_milab": None, "sel_sucursal": sucursal_id,
        "sel_tipo": tipo, "sel_desde": desde, "sel_hasta": hasta, "sel_codigo": codigo,
    }
    cod = db.fetchone("SELECT codigo FROM codigos_autorizacion WHERE sucursal_id=?", (sucursal_id,))
    if not cod or cod["codigo"] != codigo.strip():
        flash(request, "Código incorrecto", "danger")
        datos_form["flashes"] = get_flashes(request)
        return templates.TemplateResponse(request, "reportes.html", datos_form)
    if desde > hasta:
        flash(request, "La fecha inicial no puede ser posterior a la fecha final.", "danger")
        datos_form["flashes"] = get_flashes(request)
        return templates.TemplateResponse(request, "reportes.html", datos_form)
    suc = db.fetchone("SELECT nombre FROM sucursales WHERE id=?", (sucursal_id,))
    sucursal = suc["nombre"] if suc else ""

    cierres = db.fetchall(
        "SELECT fecha, venta_ids FROM cierres_diarios WHERE sucursal_id=? AND fecha BETWEEN ? AND ? ORDER BY fecha",
        (sucursal_id, desde, hasta)
    )
    ids_desde_cierres = set()
    for cierre in cierres:
        for id_texto in (cierre["venta_ids"] or "").split(","):
            if id_texto.strip().isdigit():
                ids_desde_cierres.add(int(id_texto.strip()))

    ids_por_marca = {
        int(row["id"]) for row in db.fetchall(
            """SELECT id FROM ventas
               WHERE sucursal_id=? AND date(fecha_hora) BETWEEN ? AND ?
                 AND COALESCE(activo, 0)=1 AND COALESCE(confirmado, 0)=1
                 AND UPPER(TRIM(COALESCE(estado_pago, ''))) NOT IN
                     ('COTIZACION', 'CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')
               ORDER BY fecha_hora, id""",
            (sucursal_id, desde, hasta)
        )
    }
    ids_candidatos = ids_desde_cierres | ids_por_marca
    ids_confirmados = []
    if ids_candidatos:
        placeholders_candidatos = ",".join("?" for _ in ids_candidatos)
        ids_confirmados = [
            int(row["id"]) for row in db.fetchall(
                f"""SELECT id FROM ventas
                    WHERE sucursal_id=? AND date(fecha_hora) BETWEEN ? AND ?
                      AND id IN ({placeholders_candidatos})
                      AND COALESCE(activo, 0)=1
                      AND UPPER(TRIM(COALESCE(estado_pago, ''))) NOT IN
                          ('COTIZACION', 'CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')
                    ORDER BY fecha_hora, id""",
                [sucursal_id, desde, hasta] + sorted(ids_candidatos)
            )
        ]

    if tipo.strip().upper() == "MILAB":
        detalles = []
        if ids_confirmados:
            placeholders = ",".join("?" for _ in ids_confirmados)
            detalles = db.fetchall(
                f"""SELECT v.id AS venta_id, v.folio, v.fecha_hora, p.folio AS folio_paciente,
                           p.nombre_completo AS paciente, p.fecha_nacimiento, p.edad, p.telefono,
                           vd.clave, vd.nombre AS estudio, vd.cantidad, vd.costo_unitario,
                           (vd.cantidad * vd.costo_unitario) AS costo_total
                    FROM ventas v
                    JOIN pacientes p ON p.id=v.paciente_id
                    JOIN venta_detalles vd ON vd.venta_id=v.id
                    WHERE v.sucursal_id=? AND date(v.fecha_hora) BETWEEN ? AND ?
                      AND v.id IN ({placeholders})
                      AND COALESCE(v.activo, 0)=1
                      AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN
                          ('CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')
                    ORDER BY v.fecha_hora, p.nombre_completo, vd.nombre""",
                [sucursal_id, desde, hasta] + ids_confirmados
            )
        if confirmar_pdf != "1":
            datos_form["revision_milab"] = {
                "sucursal": sucursal, "desde": desde, "hasta": hasta,
                "pacientes": len({(r["folio_paciente"], r["paciente"]) for r in detalles}),
                "detalles": detalles,
                "total_insumos": sum(float(r["costo_total"] or 0) for r in detalles),
            }
            return templates.TemplateResponse(request, "reportes.html", datos_form)
        pdf_path = generar_pdf_milab(detalles, sucursal, desde, hasta)
        return FileResponse(path=pdf_path, filename=f"MILAB_{desde}_{hasta}.pdf",
                            media_type="application/pdf", content_disposition_type="inline")

    rows = []
    if ids_confirmados:
        placeholders = ",".join("?" for _ in ids_confirmados)
        rows = db.fetchall(
            f"""SELECT v.folio, v.fecha_hora, v.total, v.monto_recibido, v.estado_pago, v.metodo_pago,
                       v.descuento_porcentaje, v.descuento_monto,
                       p.nombre_completo AS paciente, p.fecha_nacimiento, p.edad, p.telefono
                FROM ventas v
                LEFT JOIN pacientes p ON p.id=v.paciente_id
                WHERE v.sucursal_id=? AND date(v.fecha_hora) BETWEEN ? AND ?
                  AND v.id IN ({placeholders})
                  AND COALESCE(v.activo, 0)=1
                  AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN
                      ('COTIZACION', 'CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')
                ORDER BY v.fecha_hora""", [sucursal_id, desde, hasta] + ids_confirmados)
    rows = [dict(r) for r in rows]
    pdf_path = generar_pdf_reporte_lc(rows, sucursal, desde, hasta)
    return FileResponse(path=pdf_path, filename=f"LC_Lab_{desde}_{hasta}.pdf",
                        media_type="application/pdf", content_disposition_type="inline")

@app.get("/balance", response_class=HTMLResponse)
async def balance_page(request: Request, fecha: str = "", modo: str = "diario"):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    fecha = fecha or today_str()
    try:
        d = date.fromisoformat(fecha)
    except Exception:
        d = ahora_local().date()
    if modo == "semanal":
        inicio = d - timedelta(days=d.weekday())
        fin = inicio + timedelta(days=6)
        desde, hasta = inicio.isoformat(), fin.isoformat()
        titulo = f"Balance Semanal — {desde} a {hasta}"
    else:
        desde = hasta = fecha
        titulo = f"Balance Diario — {fecha}"
    datos, total_g_v, total_g_c = [], 0, 0
    for suc in db.fetchall("SELECT * FROM sucursales WHERE activa=1"):
        rows = db.fetchall(
            """SELECT v.total, v.monto_recibido, v.estado_pago, v.metodo_pago, e.nombre_completo as emp
               FROM ventas v LEFT JOIN empleados e ON e.id=v.empleado_id
               WHERE v.sucursal_id=? AND date(v.fecha_hora) BETWEEN ? AND ? AND COALESCE(v.activo, 0)=1 AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN ('CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')""",
            (suc["id"], desde, hasta))
        ventas = sum(r["total"] or 0 for r in rows)
        cobrado = sum(r["monto_recibido"] or 0 for r in rows)
        pend = sum(max(0, (r["total"] or 0) - (r["monto_recibido"] or 0)) for r in rows)
        por_met, por_emp = {}, {}
        for r in rows:
            m = r["metodo_pago"] or "Sin metodo"
            por_met[m] = por_met.get(m, 0) + (r["monto_recibido"] or 0)
            e = r["emp"] or "Sin empleado"
            por_emp[e] = por_emp.get(e, 0) + (r["total"] or 0)
        costos = db.fetchone(
            """SELECT COALESCE(SUM(vd.cantidad*vd.costo_unitario),0) as c FROM venta_detalles vd
               JOIN ventas v ON v.id=vd.venta_id WHERE v.sucursal_id=? AND date(v.fecha_hora) BETWEEN ? AND ?
               AND COALESCE(v.activo, 0)=1 AND UPPER(TRIM(COALESCE(v.estado_pago, ''))) NOT IN ('CANCELADO', 'CANCELADA', 'CANCELLED', 'CANCEL', 'ANULADO', 'ANULADA')""", (suc["id"], desde, hasta))
        costo_est = costos["c"] if costos else 0
        datos.append({"nombre": suc["nombre"], "ventas": ventas, "cobrado": cobrado, "pendiente": pend,
            "costos": costo_est, "margen": ventas - costo_est, "por_met": por_met, "por_emp": por_emp})
        total_g_v += ventas
        total_g_c += cobrado
    return templates.TemplateResponse(request, "balance.html", {"user": user, "flashes": get_flashes(request), "titulo": titulo,
        "fecha": fecha, "modo": modo, "datos": datos, "total_g_v": total_g_v, "total_g_c": total_g_c})

@app.get("/costos", response_class=HTMLResponse)
async def costos_page(request: Request, sucursal_id: str = "", desde: str = "", hasta: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    desde = desde or ahora_local().date().replace(day=1).isoformat()
    hasta = hasta or today_str()
    sql = """SELECT vd.clave, vd.nombre, vd.precio_unitario, vd.costo_unitario, SUM(vd.cantidad) as cant,
        SUM(vd.importe) as ingresos, SUM(vd.cantidad * vd.costo_unitario) as costos
        FROM venta_detalles vd JOIN ventas v ON v.id=vd.venta_id
        WHERE v.activo=1 AND v.estado_pago!='CANCELADO' AND date(v.fecha_hora) BETWEEN ? AND ?"""
    params = [desde, hasta]
    if sucursal_id and sucursal_id != "0":
        sql += " AND v.sucursal_id=?"; params.append(int(sucursal_id))
    sql += " GROUP BY vd.clave, vd.nombre, vd.precio_unitario, vd.costo_unitario ORDER BY ingresos DESC"
    rows = db.fetchall(sql, params)
    analisis = []
    for r in rows:
        m_u, pct = calcular_margen(r["precio_unitario"], r["costo_unitario"])
        analisis.append({**dict(r), "margen_u": m_u, "pct": pct, "margen_total": (r["ingresos"] or 0) - (r["costos"] or 0)})
    return templates.TemplateResponse(request, "costos.html", {"user": user, "flashes": get_flashes(request), "analisis": analisis,
        "sucursales": db.fetchall("SELECT * FROM sucursales WHERE activa=1"),
        "sucursal_id": sucursal_id or "0", "desde": desde, "hasta": hasta})

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede acceder a configuración.")
    return templates.TemplateResponse(request, "config.html", {"user": user, "flashes": get_flashes(request),
        "sucursales": db.fetchall("SELECT s.*, c.codigo FROM sucursales s LEFT JOIN codigos_autorizacion c ON c.sucursal_id=s.id WHERE s.activa=1")})

@app.post("/config/codigo")
async def config_codigo(request: Request, sucursal_id: int = Form(...), codigo: str = Form(...)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        flash(request, "Solo administradores", "danger")
        return RedirectResponse("/config", status_code=303)
    db.execute("UPDATE codigos_autorizacion SET codigo=?, updated_at=? WHERE sucursal_id=?", (codigo.strip(), now_iso(), sucursal_id))
    flash(request, "Codigo actualizado")
    return RedirectResponse("/config", status_code=303)


@app.post("/config/cambiar-password")
async def config_cambiar_password(
    request: Request,
    nip: str = Form(...),
    nueva_password: str = Form(...),
    confirmar_password: str = Form(...)
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["rol"] != "Administrador":
        raise HTTPException(status_code=403, detail="Solo el administrador puede cambiar la configuración de acceso.")
    if nip.strip() != "2026":
        flash(request, "NIP incorrecto. No se cambió la contraseña.", "danger")
        return RedirectResponse("/config", status_code=303)
    if len(nueva_password) < 6:
        flash(request, "La contraseña nueva debe tener al menos 6 caracteres.", "danger")
        return RedirectResponse("/config", status_code=303)
    if nueva_password != confirmar_password:
        flash(request, "Las contraseñas nuevas no coinciden.", "danger")
        return RedirectResponse("/config", status_code=303)
    db.execute(
        "UPDATE usuarios SET password_hash=? WHERE id=?",
        (hash_password(nueva_password), user["id"])
    )
    flash(request, "Contraseña actualizada correctamente.")
    return RedirectResponse("/config", status_code=303)


@app.get("/pdf/{venta_id}")
async def descargar_pdf(venta_id: int, request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Reutiliza el archivo existente; si Render perdió el archivo temporal,
    # reconstruye el PDF con los datos persistidos de la venta.
    venta_row = db.fetchone("SELECT * FROM ventas WHERE id=?", (venta_id,))
    if not venta_row:
        flash(request, "No se encontró la cotización solicitada.", "danger")
        return RedirectResponse("/diario", status_code=303)

    venta = dict(venta_row)
    pdf_path = str(venta.get("pdf_path") or "").strip()
    if pdf_path and Path(pdf_path).is_file():
        return FileResponse(
            path=pdf_path,
            filename=f"{venta.get('folio') or ('Venta_' + str(venta_id))}.pdf",
            media_type="application/pdf",
            content_disposition_type="inline"
        )

    try:
        paciente_row = db.fetchone("SELECT * FROM pacientes WHERE id=?", (venta["paciente_id"],))
        sucursal_row = db.fetchone("SELECT nombre FROM sucursales WHERE id=?", (venta["sucursal_id"],))
        empleado_row = db.fetchone("SELECT nombre_completo FROM empleados WHERE id=?", (venta.get("empleado_id"),)) if venta.get("empleado_id") else None
        detalles_rows = db.fetchall(
            "SELECT estudio_id, clave, nombre, cantidad, precio_unitario, costo_unitario, importe "
            "FROM venta_detalles WHERE venta_id=? ORDER BY id",
            (venta_id,)
        )
        if not paciente_row or not sucursal_row or not detalles_rows:
            raise ValueError("Faltan datos guardados de la cotización para reconstruir el PDF.")

        nuevo_pdf = generar_pdf_venta(
            venta,
            [dict(row) for row in detalles_rows],
            dict(paciente_row),
            sucursal_row["nombre"],
            empleado_row["nombre_completo"] if empleado_row else "",
            observaciones=venta.get("observaciones") or ""
        )
        db.execute("UPDATE ventas SET pdf_path=? WHERE id=?", (nuevo_pdf, venta_id))
        return FileResponse(
            path=nuevo_pdf,
            filename=f"{venta.get('folio') or ('Venta_' + str(venta_id))}.pdf",
            media_type="application/pdf",
            content_disposition_type="inline"
        )
    except Exception as e:
        print(f"Error al regenerar PDF de venta {venta_id}: {e}")
        flash(request, "No se pudo reconstruir el PDF. Verifica que la cotización conserve sus datos.", "danger")
        return RedirectResponse("/diario", status_code=303)

