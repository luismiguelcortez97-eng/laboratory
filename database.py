"""
LC Lab Web - Gestor de Base de Datos SQLite
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
import hashlib
import secrets

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "lc_lab.db"
DOCS_DIR = BASE_DIR / "documentos"
BACKUP_DIR = DATA_DIR / "backups"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


class Database:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def cursor(self):
        conn = self._connect()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur

    def fetchone(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()

    def fetchall(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

    def _init_db(self):
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT
                )
            """)
            if not cur.execute("SELECT 1 FROM schema_version WHERE id=1").fetchone():
                cur.execute("INSERT INTO schema_version (id, version, updated_at) VALUES (1, 1, ?)",
                            (datetime.now().isoformat(),))

            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    nombre_completo TEXT NOT NULL,
                    rol TEXT NOT NULL DEFAULT 'Recepcionista',
                    empleado_id INTEGER,
                    activo INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS sucursales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL UNIQUE,
                    codigo TEXT NOT NULL UNIQUE,
                    activa INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS empleados (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_completo TEXT NOT NULL,
                    puesto TEXT NOT NULL,
                    activo INTEGER NOT NULL DEFAULT 1,
                    fecha_alta TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pacientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folio TEXT NOT NULL UNIQUE,
                    nombre_completo TEXT NOT NULL,
                    edad INTEGER,
                    sexo TEXT,
                    fecha_nacimiento TEXT,
                    telefono TEXT,
                    sucursal_id INTEGER NOT NULL,
                    empleado_id INTEGER,
                    fecha_registro TEXT NOT NULL,
                    fecha_entrega_resultados TEXT,
                    modalidad_entrega TEXT,
                    observaciones TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY (sucursal_id) REFERENCES sucursales(id),
                    FOREIGN KEY (empleado_id) REFERENCES empleados(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS estudios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clave TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    precio_venta REAL NOT NULL DEFAULT 0,
                    costo_insumo REAL NOT NULL DEFAULT 0,
                    activo INTEGER NOT NULL DEFAULT 1,
                    sucursal_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    UNIQUE(clave, sucursal_id),
                    FOREIGN KEY (sucursal_id) REFERENCES sucursales(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS ventas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folio TEXT NOT NULL UNIQUE,
                    paciente_id INTEGER NOT NULL,
                    sucursal_id INTEGER NOT NULL,
                    empleado_id INTEGER,
                    fecha_hora TEXT NOT NULL,
                    total REAL NOT NULL DEFAULT 0,
                    estado_pago TEXT NOT NULL DEFAULT 'PENDIENTE',
                    metodo_pago TEXT,
                    monto_recibido REAL NOT NULL DEFAULT 0,
                    saldo_pendiente REAL NOT NULL DEFAULT 0,
                    observaciones TEXT,
                    pdf_path TEXT,
                    activo INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
                    FOREIGN KEY (sucursal_id) REFERENCES sucursales(id),
                    FOREIGN KEY (empleado_id) REFERENCES empleados(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS venta_detalles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER NOT NULL,
                    estudio_id INTEGER,
                    clave TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    cantidad REAL NOT NULL DEFAULT 1,
                    precio_unitario REAL NOT NULL,
                    costo_unitario REAL NOT NULL DEFAULT 0,
                    importe REAL NOT NULL,
                    FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pagos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER NOT NULL,
                    monto REAL NOT NULL,
                    metodo_pago TEXT NOT NULL,
                    fecha_hora TEXT NOT NULL,
                    empleado_id INTEGER,
                    observaciones TEXT,
                    FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS auditoria (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tabla TEXT NOT NULL,
                    registro_id INTEGER NOT NULL,
                    accion TEXT NOT NULL,
                    datos_anteriores TEXT,
                    datos_nuevos TEXT,
                    usuario_id INTEGER,
                    fecha_hora TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS configuracion (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL,
                    updated_at TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS codigos_autorizacion (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sucursal_id INTEGER NOT NULL UNIQUE,
                    codigo TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY (sucursal_id) REFERENCES sucursales(id)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_pac_suc ON pacientes(sucursal_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ven_suc ON ventas(sucursal_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ven_fecha ON ventas(fecha_hora)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_est_suc ON estudios(sucursal_id)")

        self._seed()

    def _seed(self):
        now = datetime.now().isoformat()
        with self.cursor() as cur:
            if cur.execute("SELECT COUNT(*) as c FROM sucursales").fetchone()["c"] == 0:
                cur.execute("INSERT INTO sucursales (nombre, codigo, activa, created_at) VALUES (?,?,1,?)",
                            ("Ejido Hermosillo", "EJ", now))
                cur.execute("INSERT INTO sucursales (nombre, codigo, activa, created_at) VALUES (?,?,1,?)",
                            ("Tecolotes", "TC", now))

            if cur.execute("SELECT COUNT(*) as c FROM empleados").fetchone()["c"] == 0:
                cur.execute(
                    "INSERT INTO empleados (nombre_completo, puesto, activo, fecha_alta, created_at) VALUES (?,?,1,?,?)",
                    ("Administrador LC Lab", "Administrador", now[:10], now)
                )

            if cur.execute("SELECT COUNT(*) as c FROM usuarios").fetchone()["c"] == 0:
                emp = cur.execute("SELECT id FROM empleados LIMIT 1").fetchone()
                pwd = hash_password("admin123")
                cur.execute(
                    """INSERT INTO usuarios (username, password_hash, nombre_completo, rol, empleado_id, activo, created_at)
                       VALUES (?,?,?,?,?,1,?)""",
                    ("admin", pwd, "Administrador LC Lab", "Administrador", emp["id"] if emp else None, now)
                )

            if cur.execute("SELECT COUNT(*) as c FROM codigos_autorizacion").fetchone()["c"] == 0:
                ej = cur.execute("SELECT id FROM sucursales WHERE codigo='EJ'").fetchone()
                tc = cur.execute("SELECT id FROM sucursales WHERE codigo='TC'").fetchone()
                if ej:
                    cur.execute("INSERT INTO codigos_autorizacion (sucursal_id, codigo, updated_at) VALUES (?,?,?)",
                                (ej["id"], "LC2024EJ", now))
                if tc:
                    cur.execute("INSERT INTO codigos_autorizacion (sucursal_id, codigo, updated_at) VALUES (?,?,?)",
                                (tc["id"], "LC2024TC", now))

            defaults = {
                "nombre_laboratorio": "LC Lab",
                "version_app": "2.0.0-web",
            }
            for k, v in defaults.items():
                if not cur.execute("SELECT 1 FROM configuracion WHERE clave=?", (k,)).fetchone():
                    cur.execute("INSERT INTO configuracion (clave, valor, updated_at) VALUES (?,?,?)",
                                (k, v, now))

    def generar_folio(self, prefijo="V"):
        hoy = datetime.now().strftime("%Y%m%d")
        tabla = "pacientes" if prefijo == "P" else "ventas"
        with self.cursor() as cur:
            c = cur.execute(f"SELECT COUNT(*) as c FROM {tabla} WHERE folio LIKE ?", (f"{prefijo}{hoy}%",)).fetchone()["c"]
            return f"{prefijo}{hoy}{c + 1:04d}"

    def log_auditoria(self, tabla, registro_id, accion, anteriores=None, nuevos=None, usuario_id=None):
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO auditoria (tabla, registro_id, accion, datos_anteriores, datos_nuevos, usuario_id, fecha_hora)
                   VALUES (?,?,?,?,?,?,?)""",
                (tabla, registro_id, accion,
                 json.dumps(anteriores, ensure_ascii=False) if anteriores else None,
                 json.dumps(nuevos, ensure_ascii=False) if nuevos else None,
                 usuario_id, datetime.now().isoformat())
            )


def hash_password(password: str) -> str:
    """Hash seguro con PBKDF2-SHA256."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"pbkdf2:{salt}:{h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, hash_hex = stored.split(":")
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return h.hex() == hash_hex
    except Exception:
        return False


db = Database()
