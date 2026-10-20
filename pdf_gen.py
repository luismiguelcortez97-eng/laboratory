"""Generación de PDFs para LC Lab Web"""
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from database import DOCS_DIR

AZUL = colors.HexColor("#1a5276")
AZUL_CLARO = colors.HexColor("#d4e6f1")
GRIS = colors.HexColor("#566573")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="Titulo", parent=s["Heading1"], fontSize=16, textColor=AZUL,
                         alignment=TA_CENTER, spaceAfter=4, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle(name="Sub", parent=s["Normal"], fontSize=10, textColor=GRIS,
                         alignment=TA_CENTER, spaceAfter=6))
    s.add(ParagraphStyle(name="Sec", parent=s["Heading2"], fontSize=11, textColor=AZUL,
                         spaceBefore=8, spaceAfter=4, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle(name="Sm", parent=s["Normal"], fontSize=9, leading=12))
    s.add(ParagraphStyle(name="Der", parent=s["Normal"], fontSize=9, alignment=TA_RIGHT))
    s.add(ParagraphStyle(name="Cen", parent=s["Normal"], fontSize=9, alignment=TA_CENTER))
    return s


def generar_pdf_venta(venta, detalles, paciente, sucursal, empleado):
    folio = venta.get("folio", "X")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DOCS_DIR / f"Venta_{folio}_{ts}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter,
                            rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    st = _styles()
    story = []
    story.append(Paragraph("LC LAB", st["Titulo"]))
    story.append(Paragraph("Laboratorio Clínico", st["Sub"]))
    story.append(Paragraph(f"Sucursal: {sucursal}", st["Cen"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=AZUL, spaceAfter=8))

    estado = venta.get("estado_pago", "PENDIENTE")
    info = [
        [Paragraph(f"<b>Folio:</b> {folio}", st["Sm"]),
         Paragraph(f"<b>Fecha:</b> {str(venta.get('fecha_hora',''))[:19].replace('T',' ')}", st["Der"])],
        [Paragraph(f"<b>Estado:</b> {estado}", st["Sm"]),
         Paragraph(f"<b>Empleado:</b> {empleado or '—'}", st["Der"])],
    ]
    t = Table(info, colWidths=[9*cm, 9*cm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Datos del Paciente", st["Sec"]))
    pac = [
        [Paragraph(f"<b>Nombre:</b> {paciente.get('nombre_completo','')}", st["Sm"]),
         Paragraph(f"<b>Edad:</b> {paciente.get('edad','—')}", st["Sm"])],
        [Paragraph(f"<b>Sexo:</b> {paciente.get('sexo','—')}", st["Sm"]),
         Paragraph(f"<b>Teléfono:</b> {paciente.get('telefono','—')}", st["Sm"])],
    ]
    tp = Table(pac, colWidths=[9*cm, 9*cm])
    tp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AZUL_CLARO),
        ("BOX", (0, 0), (-1, -1), 0.5, AZUL),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tp)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Estudios Solicitados", st["Sec"]))
    data = [[Paragraph("<b>Clave</b>", st["Cen"]), Paragraph("<b>Estudio</b>", st["Cen"]),
             Paragraph("<b>Cant.</b>", st["Cen"]), Paragraph("<b>P.Unit.</b>", st["Cen"]),
             Paragraph("<b>Importe</b>", st["Cen"])]]
    for d in detalles:
        data.append([
            Paragraph(str(d.get("clave", "")), st["Sm"]),
            Paragraph(str(d.get("nombre", "")), st["Sm"]),
            Paragraph(f"{float(d.get('cantidad',1)):.0f}", st["Cen"]),
            Paragraph(f"${float(d.get('precio_unitario',0)):.2f}", st["Der"]),
            Paragraph(f"${float(d.get('importe',0)):.2f}", st["Der"]),
        ])
    te = Table(data, colWidths=[2.5*cm, 8*cm, 2*cm, 2.8*cm, 2.7*cm])
    te.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aab7b8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, AZUL_CLARO]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(te)
    story.append(Spacer(1, 8))

    total = float(venta.get("total", 0))
    recibido = float(venta.get("monto_recibido", 0))
    saldo = float(venta.get("saldo_pendiente", total - recibido))
    tot = [[Paragraph("<b>TOTAL</b>", st["Sm"]), Paragraph(f"<b>${total:,.2f}</b>", st["Der"])]]
    if recibido > 0:
        tot.append([Paragraph("Monto recibido", st["Sm"]), Paragraph(f"${recibido:,.2f}", st["Der"])])
    if saldo > 0.01:
        tot.append([Paragraph("<b>Saldo pendiente</b>", st["Sm"]), Paragraph(f"<b>${saldo:,.2f}</b>", st["Der"])])
    if venta.get("metodo_pago"):
        tot.append([Paragraph("Método de pago", st["Sm"]), Paragraph(str(venta["metodo_pago"]), st["Der"])])
    tt = Table(tot, colWidths=[12*cm, 6*cm])
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL_CLARO), ("BOX", (0, 0), (-1, -1), 0.8, AZUL),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(tt)
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRIS, spaceAfter=6))
    story.append(Paragraph("Documento generado por LC Lab. Conserve este comprobante.", st["Cen"]))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", st["Cen"]))
    doc.build(story)
    return str(path)


def generar_pdf_milab(detalles, sucursal, desde, hasta):
    """PDF de MILAB con lista de pacientes y únicamente costos de insumo."""
    from xml.sax.saxutils import escape
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DOCS_DIR / f"MILAB_{desde}_{hasta}_{ts}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=1.0*cm, leftMargin=1.0*cm, topMargin=1.0*cm, bottomMargin=1.0*cm)
    st = _styles()
    story = [Paragraph("LC LAB", st["Titulo"]), Paragraph("RELACIÓN DE ESTUDIOS PARA MILAB", st["Sub"]), Paragraph("Sucursal: " + escape(str(sucursal)), st["Cen"]), Paragraph("Periodo: " + escape(str(desde)) + " al " + escape(str(hasta)), st["Cen"]), Spacer(1, 8), HRFlowable(width="100%", thickness=1.5, color=AZUL, spaceAfter=8)]
    data = [[Paragraph("<b>Fecha</b>", st["Cen"]), Paragraph("<b>Paciente / folio</b>", st["Cen"]), Paragraph("<b>Estudio</b>", st["Cen"]), Paragraph("<b>Cant.</b>", st["Cen"]), Paragraph("<b>Insumo unit.</b>", st["Cen"]), Paragraph("<b>Total insumo</b>", st["Cen"])]]
    total = 0.0
    pacientes = set()
    for r in detalles:
        nombre = str(r["paciente"] or "")
        folio_pac = str(r["folio_paciente"] or "")
        cantidad = float(r["cantidad"] or 0)
        costo = float(r["costo_unitario"] or 0)
        subtotal = float(r["costo_total"] or 0)
        total += subtotal
        pacientes.add((folio_pac, nombre))
        data.append([Paragraph(escape(str(r["fecha_hora"] or "")[:10]), st["Sm"]), Paragraph(escape(nombre) + "<br/><font size='7'>" + escape(folio_pac) + " · " + escape(str(r["folio"] or "")) + "</font>", st["Sm"]), Paragraph(escape(str(r["estudio"] or "")), st["Sm"]), Paragraph(f"{cantidad:g}", st["Cen"]), Paragraph(f"MXN {costo:,.2f}", st["Der"]), Paragraph(f"MXN {subtotal:,.2f}", st["Der"])])
    if not detalles:
        data.append([Paragraph("Sin estudios registrados en el periodo seleccionado.", st["Sm"]), "", "", "", "", ""])
    tabla = Table(data, repeatRows=1, colWidths=[1.8*cm, 4.8*cm, 4.4*cm, 1.2*cm, 2.6*cm, 2.8*cm])
    tabla.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#aab7b8")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, AZUL_CLARO]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([tabla, Spacer(1, 10)])
    resumen = [[Paragraph("<b>Pacientes</b>", st["Sm"]), Paragraph(str(len(pacientes)), st["Der"])], [Paragraph("<b>Estudios</b>", st["Sm"]), Paragraph(str(len(detalles)), st["Der"])], [Paragraph("<b>TOTAL DE INSUMOS MILAB</b>", st["Sm"]), Paragraph(f"<b>MXN {total:,.2f}</b>", st["Der"])]]
    rt = Table(resumen, colWidths=[12*cm, 5.5*cm], hAlign="RIGHT")
    rt.setStyle(TableStyle([("BACKGROUND", (0, 2), (-1, 2), AZUL_CLARO), ("BOX", (0, 0), (-1, -1), 0.7, AZUL), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([rt, Spacer(1, 10), Paragraph("Este reporte muestra exclusivamente costos de insumo; no incluye precios de venta ni cobros al paciente.", st["Cen"]), Paragraph("Generado el " + datetime.now().strftime("%d/%m/%Y %H:%M:%S"), st["Cen"])])
    doc.build(story)
    return str(path)