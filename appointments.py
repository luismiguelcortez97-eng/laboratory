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
def _horario_config():
 def valor(clave, defecto):
  r=db.fetchone("SELECT valor FROM configuracion_citas WHERE clave=?",(clave,))
  return str(r['valor']) if r and r['valor'] else defecto
 dias_raw=valor('dias_trabajo','0,1,2,3,4,5,6')
 try:
  dias=sorted({int(d) for d in dias_raw.split(',') if d.strip() and 0<=int(d)<7})
 except ValueError:
  dias=[0,1,2,3,4,5,6]
 return {'inicio':valor('hora_inicio','08:00'),'fin':valor('hora_fin','16:00'),'intervalo':int(valor('intervalo_minutos','30')),'dias':dias}
def _slots():
 cfg=_horario_config()
 inicio=datetime.strptime(cfg['inicio'],'%H:%M')
 fin=datetime.strptime(cfg['fin'],'%H:%M')
 paso=cfg['intervalo']
 actual=inicio
 slots=[]
 while actual<fin:
  slots.append(actual.strftime('%H:%M'))
  from datetime import timedelta
  actual += timedelta(minutes=paso)
 return slots
def _ctx(request, **kw):
 d={'request':request,'sucursales':db.fetchall("SELECT id,nombre FROM sucursales WHERE activa=1 ORDER BY nombre"),'hoy':today_str(),'whatsapp_url':_url(),'horario_config':_horario_config(),'error':None,'cita_guardada':None,'verificacion':None,'verificacion_error':None}
 d.update(kw); return d

@router.get('/pedir-cita', response_class=HTMLResponse)
async def pedir_cita(request:Request):
 return templates.TemplateResponse(request,'pedir_cita.html',_ctx(request))

@router.get('/api/citas/ocupacion')
async def ocupacion(fecha:str,sucursal_id:int):
 try:
  dia=date.fromisoformat(fecha)
 except (ValueError,TypeError):
  raise HTTPException(status_code=400,detail='Fecha inválida')
 if dia.isoformat()!=fecha:
  raise HTTPException(status_code=400,detail='Fecha inválida')
 if dia<ahora_local().date():
  raise HTTPException(status_code=400,detail='La fecha de la cita no puede estar en el pasado.')
 if dia.weekday() not in _horario_config()['dias']:
  raise HTTPException(status_code=400,detail='Ese día no se reciben citas. Elige un día laboral disponible.')
 if not db.fetchone('SELECT id FROM sucursales WHERE id=? AND activa=1',(sucursal_id,)):
  raise HTTPException(status_code=400,detail='Selecciona una sucursal válida.')
 rows=db.fetchall('SELECT hora FROM citas WHERE fecha=? AND sucursal_id=?',(fecha,sucursal_id))
 ocupadas={str(r['hora'])[:5] for r in rows}
 slots=_slots()
 if dia==ahora_local().date():
  slots=[s for s in slots if s>ahora_local().strftime('%H:%M')]
 disponibles=[s for s in slots if s not in ocupadas]
 return {'fecha':fecha,'sucursal_id':sucursal_id,'horarios':disponibles,'ocupadas':sorted(ocupadas)}

@router.post('/api/citas/guardar',response_class=HTMLResponse)
async def guardar(request:Request,nombre_completo:str=Form(...),edad:int=Form(...),fecha_nacimiento:str=Form(...),telefono:str=Form(...),sucursal_id:int=Form(...),fecha:str=Form(...),hora:str=Form(...)):
 datos={'nombre_completo':nombre_completo.strip(),'edad':edad,'fecha_nacimiento':fecha_nacimiento,'telefono':telefono.strip(),'sucursal_id':sucursal_id,'fecha':fecha,'hora':hora}
 error=None
 try:
  nacimiento=date.fromisoformat(fecha_nacimiento); dia=date.fromisoformat(fecha); datetime.strptime(hora,'%H:%M')
  if nacimiento.isoformat()!=fecha_nacimiento or dia.isoformat()!=fecha: raise ValueError('Fecha inválida')
  if len(datos['nombre_completo'])<3: error='Escribe tu nombre completo.'
  elif edad<0 or edad>120: error='Verifica la edad ingresada.'
  elif nacimiento>ahora_local().date() or dia<ahora_local().date(): error='Revisa las fechas ingresadas.'
  elif dia.weekday() not in _horario_config()['dias']: error='Ese día no se reciben citas. Elige un día laboral disponible.'
  elif len(''.join(c for c in telefono if c.isdigit()))<10: error='Escribe un teléfono válido de al menos 10 dígitos.'
  elif hora not in _slots() or (dia==ahora_local().date() and hora<=ahora_local().strftime('%H:%M')): error='Selecciona un horario válido y futuro.'
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
async def agenda(request:Request,fecha:str='',sucursal_id:int=0,periodo:str='dia'):
 from main import get_user,get_flashes
 from datetime import timedelta
 from calendar import monthrange
 user=get_user(request)
 if not user: return RedirectResponse('/login',status_code=303)
 try:
  ancla=date.fromisoformat(fecha) if fecha else ahora_local().date()
 except (ValueError,TypeError):
  ancla=ahora_local().date()
 if periodo not in ('dia','semana','mes'): periodo='dia'
 if periodo=='semana':
  inicio=ancla-timedelta(days=ancla.weekday()); fin=inicio+timedelta(days=6)
  anterior=inicio-timedelta(days=7); siguiente=inicio+timedelta(days=7)
 elif periodo=='mes':
  inicio=ancla.replace(day=1); fin=ancla.replace(day=monthrange(ancla.year,ancla.month)[1])
  anterior=(inicio-timedelta(days=1)).replace(day=1)
  siguiente=(fin+timedelta(days=1)).replace(day=1)
 else:
  inicio=fin=ancla; anterior=ancla-timedelta(days=1); siguiente=ancla+timedelta(days=1)
 rows=db.fetchall("SELECT c.folio,c.nombre_completo,c.edad,c.fecha_nacimiento,c.telefono,c.fecha,c.hora,s.nombre AS sucursal FROM citas c JOIN sucursales s ON s.id=c.sucursal_id WHERE c.fecha>=? AND c.fecha<=? AND (?=0 OR c.sucursal_id=?) ORDER BY c.fecha,c.hora",(inicio.isoformat(),fin.isoformat(),sucursal_id,sucursal_id))
 return templates.TemplateResponse(request,'citas.html',{'request':request,'user':user,'flashes':get_flashes(request),'citas':rows,'fecha':ancla.isoformat(),'fecha_inicio':inicio.isoformat(),'fecha_fin':fin.isoformat(),'fecha_anterior':anterior.isoformat(),'fecha_siguiente':siguiente.isoformat(),'periodo':periodo,'sucursal_id':sucursal_id,'sucursales':db.fetchall('SELECT id,nombre FROM sucursales WHERE activa=1 ORDER BY nombre'),'whatsapp_numero':_numero(),'horario_config':_horario_config()})

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


@router.post('/citas/horario')
async def guardar_horario(request:Request,hora_inicio:str=Form(...),hora_fin:str=Form(...),intervalo_minutos:int=Form(...),dias_trabajo:list[int]=Form(...)):
 from main import get_user,flash
 user=get_user(request)
 if not user: return RedirectResponse('/login',status_code=303)
 if user['rol']!='Administrador': raise HTTPException(status_code=403,detail='Solo el administrador puede cambiar el horario de citas.')
 try:
  inicio=datetime.strptime(hora_inicio,'%H:%M')
  fin=datetime.strptime(hora_fin,'%H:%M')
 except ValueError:
  raise HTTPException(status_code=400,detail='Selecciona horas válidas.')
 if inicio>=fin: raise HTTPException(status_code=400,detail='La hora de cierre debe ser posterior a la hora de inicio.')
 if intervalo_minutos not in (10,15,20,30,60): raise HTTPException(status_code=400,detail='Selecciona un intervalo válido.')
 if not dias_trabajo or any(d not in range(7) for d in dias_trabajo): raise HTTPException(status_code=400,detail='Selecciona al menos un día laboral.')
 valores=[('hora_inicio',hora_inicio),('hora_fin',hora_fin),('intervalo_minutos',str(intervalo_minutos)),('dias_trabajo',','.join(str(d) for d in sorted(set(dias_trabajo))))]
 for clave,valor in valores:
  db.execute("INSERT INTO configuracion_citas(clave,valor,updated_at) VALUES(?,?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor,updated_at=excluded.updated_at",(clave,valor,now_iso()))
 flash(request,'Días y horario de citas actualizados. El portal público ya usa la nueva configuración.')
 return RedirectResponse('/citas',status_code=303)
