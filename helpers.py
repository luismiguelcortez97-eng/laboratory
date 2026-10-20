"""Utilidades LC Lab Web"""
from datetime import datetime, date
from zoneinfo import ZoneInfo
import re

# Zona horaria oficial de Mexicali, Baja California.
ZONA_HORARIA = ZoneInfo("America/Tijuana")


def ahora_local():
    return datetime.now(ZONA_HORARIA)


METODOS_PAGO = ["Efectivo", "Transferencia", "Tarjeta", "Otro"]
ESTADOS_PAGO = ["PENDIENTE", "PARCIAL", "PAGADO", "CANCELADO"]
SEXOS = ["Masculino", "Femenino", "Otro"]
PUESTOS = ["Administrador", "Encargado de sucursal", "Recepcionista", "Laboratorista", "Médico", "Otro"]
ROLES = ["Administrador", "Encargado de sucursal", "Recepcionista", "Laboratorista"]


def now_iso():
    return ahora_local().isoformat(timespec="seconds")


def today_str():
    return ahora_local().date().isoformat()


def format_money(v):
    try:
        return f"${float(v or 0):,.2f}"
    except Exception:
        return "$0.00"


def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def format_dt(iso):
    if not iso:
        return ""
    try:
        valor = datetime.fromisoformat(iso)
        if valor.tzinfo is not None:
            valor = valor.astimezone(ZONA_HORARIA)
        return valor.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(iso)[:19]


def calcular_margen(precio, costo):
    p, c = safe_float(precio), safe_float(costo)
    m = p - c
    pct = (m / p * 100) if p > 0 else 0
    return round(m, 2), round(pct, 2)
