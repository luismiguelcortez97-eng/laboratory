"""Portal público para agendar citas y agenda privada del personal."""
import os, secrets
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from database import db
from helpers import now_iso, today_str, ahora_local

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
db.execute("""CREATE TABLE IF NOT EXISTS citas (
 id INTEGER PRIMARY KEY AUTOINCREMENT, folio TEXT NOT NULL UNIQUE,
 nombre_completo TEXT NOT NULL, edad INTEGER NOT NULL, fecha_nacimiento TEXT NOT NULL,
 telefono TEXT NOT NULL, sucursal_id INTEGER NOT NULL, fecha TEXT NOT NULL, hora TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(sucursal_id, fecha, hora))""")
db.execute("""CREATE TABLE IF NOT EXISTS configuracion_citas (
 clave TEXT PRIMARY KEY, valor TEXT NOT NULL DEFAULT '', updated_at TEXT)""")

def _numero():
 r=db.fetchone("SELECT valor FROM configuracion_citas WHERE clave='whatsapp'")
 return ''.join(c for c in str(r['valor'] if r else os.environ.get('WHATSAPP_COTIZACIONES','')) if c.isdigit())
def _url():
 n=_numero()
 return 'https://wa.me/'+n+'?text='+quote('Hola, deseo solicitar una cotización de estudios de laboratorio.') if n else ''
def _slots():
 return [f'{h:02d}:{m:02d}' for h in range(8,17) for m in (0,30) if (h,m)!=(16,30)]
def _ctx(request, **kw):
 d={'request':request,'sucursales':db.fetchall("SELECT id,nombre FROM sucursales WHERE activa=1 ORDER BY nombre"),'hoy':today_str(),'whatsapp_url':_url(),'error':None,'cita_guardada':None,'verificacion':None,'verificacion_error':None}
 d.update(kw); return d

@router.get('/pedir-cita', response_class=HTMLResponse)
async def pedir_cita(request:Request):
 return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request))

@router.get('/api/citas/ocupacion')
async def ocupacion(fecha:str,sucursal_id:int):
 try: dia=date.fromisoformat(fecha)
 except ValueError: raise HTTPException(status_code=400,detail='Fecha inválida')
 if dia<date.today(): raise HTTPException(status_code=400,detail='Fecha pasada')
 rows=db.fetchall('SELECT hora FROM citas WHERE fecha=? AND sucursal_id=?',(fecha,sucursal_id))
 slots=_slots()
 if fecha==today_str(): slots=[s for s in slots if s>ahora_local().strftime('%H:%M')]
 return {'horarios':slots,'ocupadas':[str(r['hora'])[:5] for r in rows]}

@router.post('/api/citas/guardar',response_class=HTMLResponse)
async def guardar(request:Request,nombre_completo:str=Form(...),edad:int=Form(...),fecha_nacimiento:str=Form(...),telefono:str=Form(...),sucursal_id:int=Form(...),fecha:str=Form(...),hora:str=Form(...)):
 datos={'nombre_completo':nombre_completo.strip(),'edad':edad,'fecha_nacimiento':fecha_nacimiento,'telefono':telefono.strip(),'sucursal_id':sucursal_id,'fecha':fecha,'hora':hora}
 error=None
 try:
  nacimiento=date.fromisoformat(fecha_nacimiento); dia=date.fromisoformat(fecha); datetime.strptime(hora,'%H:%M')
  if len(datos['nombre_completo'])<3: error='Escribe tu nombre completo.'
  elif edad<0 or edad>120: error='Verifica la edad ingresada.'
  elif nacimiento>date.today() or dia<date.today(): error='Revisa las fechas ingresadas.'
  elif len(''.join(c for c in telefono if c.isdigit()))<10: error='Escribe un teléfono válido de al menos 10 dígitos.'
  elif hora not in _slots() or (dia==date.today() and hora<=ahora_local().strftime('%H:%M')): error='Selecciona un horario válido y futuro.'
  elif not db.fetchone('SELECT id FROM sucursales WHERE id=? AND activa=1',(sucursal_id,)): error='Selecciona una sucursal válida.'
 except (ValueError,TypeError): error='Revisa las fechas y la hora.'
 if error: return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request,error=error,datos=datos),status_code=400)
 folio='C'+str(secrets.randbelow(900000)+100000); timestamp=now_iso()
 try:
  with db.cursor() as cur:
   cur.execute('INSERT INTO citas (folio,nombre_completo,edad,fecha_nacimiento,telefono,sucursal_id,fecha,hora,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(folio,datos['nombre_completo'],edad,fecha_nacimiento,telefono.strip(),sucursal_id,fecha,hora,timestamp))
   pf=db.generar_folio('P')
   cur.execute('INSERT INTO pacientes (folio,nombre_completo,edad,fecha_nacimiento,telefono,sucursal_id,fecha_registro,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',(pf,datos['nombre_completo'],edad,fecha_nacimiento,telefono.strip(),sucursal_id,timestamp,timestamp,timestamp))
 except Exception:
  return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request,error='Ese horario acaba de ocuparse o no pudimos guardar la cita. Actualiza los horarios e inténtalo otra vez.',datos=datos),status_code=409)
 suc=db.fetchone('SELECT nombre FROM sucursales WHERE id=?',(sucursal_id,))
 return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request,cita_guardada={'folio':folio,'fecha':fecha,'hora':hora,'sucursal':suc['nombre'] if suc else ''}))

@router.post('/api/citas/verificar',response_class=HTMLResponse)
async def verificar(request:Request,folio:str=Form(...),telefono:str=Form(...)):
 codigo=folio.strip().upper(); tel=''.join(c for c in telefono if c.isdigit())
 rows=db.fetchall('SELECT fecha,hora,sucursal_id,telefono FROM citas WHERE UPPER(folio)=?',(codigo,))
 cita=next((r for r in rows if ''.join(c for c in str(r['telefono']) if c.isdigit())==tel),None)
 if not cita: return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request,verificacion_error='No encontramos una cita con ese folio y teléfono.'))
 suc=db.fetchone('SELECT nombre FROM sucursales WHERE id=?',(cita['sucursal_id'],))
 return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request,verificacion={'fecha':cita['fecha'],'hora':str(cita['hora'])[:5],'sucursal':suc['nombre'] if suc else ''}))

@router.get('/citas',response_class=HTMLResponse)
async def agenda(request:Request,fecha:str='',sucursal_id:int=0):
 from main import get_user,get_flashes
 user=get_user(request)
 if not user: return RedirectResponse('/login',status_code=303)
 fecha=fecha or today_str()
 rows=db.fetchall("SELECT c.folio,c.nombre_completo,c.edad,c.fecha_nacimiento,c.telefono,c.fecha,c.hora,s.nombre AS sucursal FROM citas c JOIN sucursales s ON s.id=c.sucursal_id WHERE c.fecha=? AND (?=0 OR c.sucursal_id=?) ORDER BY c.hora",(fecha,sucursal_id,sucursal_id))
 return templates.TemplateResponse(request,'citas.html',{'request':request,'user':user,'flashes':get_flashes(request),'citas':rows,'fecha':fecha,'sucursal_id':sucursal_id,'sucursales':db.fetchall('SELECT id,nombre FROM sucursales WHERE activa=1 ORDER BY nombre'),'whatsapp_numero':_numero()})

@router.post('/citas/whatsapp')
async def guardar_whatsapp(request:Request,numero:str=Form('')):
 from main import get_user,flash
 user=get_user(request)
 if not user: return RedirectResponse('/login',status_code=303)
 if user['rol']!='Administrador': raise HTTPException(status_code=403,detail='Solo el administrador puede cambiar este número.')
 limpio=''.join(c for c in numero if c.isdigit())
 if limpio and len(limpio)<10: raise HTTPException(status_code=400,detail='Incluye lada internacional y al menos 10 dígitos.')
 db.execute("INSERT INTO configuracion_citas(clave,valor,updated_at) VALUES(?,?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor,updated_at=excluded.updated_at",('whatsapp',limpio,now_iso()))
 flash(request,'Número de WhatsApp actualizado.')
 return RedirectResponse('/citas',status_code=303)
