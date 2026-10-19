# LC Lab Web — Sistema de Laboratorio Clínico

Versión **web** de LC Lab. Se abre con un enlace en cualquier navegador (computadora, tablet o celular).

## Características

- Login con usuario y contraseña
- Panel de inicio con indicadores del día
- Registro de pacientes
- Cotización / venta de estudios con PDF
- Registro diario por sucursal (Ejido Hermosillo y Tecolotes)
- Catálogo de estudios independiente por sucursal
- Control de costos y margen bruto
- Empleados
- Reportes LC Lab y MILAB protegidos con código
- Balance diario y semanal
- Diseño responsive (funciona en iPhone y Android)

## Requisitos

- Python 3.10 o superior

## Instalación

```bash
cd lc_lab_web
python -m venv venv

# Windows:
venv\Scripts\activate

# Linux / Mac:
source venv/bin/activate

pip install -r requirements.txt
```

## Ejecutar

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Luego abre en el navegador:

- En la misma computadora: **http://localhost:8000**
- Desde otro dispositivo en la misma red: **http://IP-DE-LA-PC:8000**  
  (ejemplo: http://192.168.1.50:8000)

## Usuario inicial

| Campo        | Valor      |
|--------------|------------|
| Usuario      | `admin`    |
| Contraseña   | `admin123` |

**Cambia la contraseña en producción.**

## Códigos de autorización (reportes)

| Sucursal           | Código     |
|--------------------|------------|
| Ejido Hermosillo   | `LC2024EJ` |
| Tecolotes          | `LC2024TC` |

## Estructura

```
lc_lab_web/
├── app/
│   ├── main.py          # Aplicación FastAPI
│   ├── database.py      # SQLite
│   ├── helpers.py
│   ├── pdf_gen.py
│   ├── templates/       # HTML
│   └── static/
├── data/                # Base de datos
├── documentos/          # PDFs generados
├── requirements.txt
└── README.md
```

## Acceso desde celular

1. Asegúrate de que el celular esté en la misma red Wi-Fi que la computadora donde corre LC Lab.
2. Averigua la IP de la computadora (`ipconfig` en Windows).
3. En el celular abre: `http://ESA-IP:8000`
4. En iPhone: Safari → Compartir → **Añadir a pantalla de inicio** (queda como app).

## Notas

- La base de datos se crea automáticamente la primera vez.
- Los datos se conservan entre reinicios.
- Para producción se recomienda HTTPS y cambiar la `secret_key` de las sesiones.
