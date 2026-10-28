"""Generación de PDFs para LC Lab Web"""
from datetime import datetime
from helpers import ahora_local
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
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


def generar_pdf_venta(venta, detalles, paciente, sucursal, empleado, observaciones=""):
    folio = venta.get("folio", "X")
    ts = ahora_local().strftime("%Y%m%d_%H%M%S")
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
    subtotal = round(total + float(venta.get("descuento_monto", 0) or 0), 2)
    porcentaje_descuento = float(venta.get("descuento_porcentaje", 0) or 0)
    descuento_monto = float(venta.get("descuento_monto", 0) or 0)
    tot = []
    if descuento_monto > 0:
        tot.append([Paragraph("Subtotal", st["Sm"]), Paragraph(f"${subtotal:,.2f}", st["Der"])])
        tot.append([Paragraph(f"Descuento ({porcentaje_descuento:g}%)", st["Sm"]), Paragraph(f"-${descuento_monto:,.2f}", st["Der"])])
    tot.append([Paragraph("<b>TOTAL</b>", st["Sm"]), Paragraph(f"<b>${total:,.2f}</b>", st["Der"])])
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

    # Notas escritas por el usuario para esta cotización/venta.
    # Se escapan caracteres HTML y se conservan los saltos de línea en el PDF.
    nota = str(observaciones or venta.get("observaciones") or "").strip()
    if nota:
        from xml.sax.saxutils import escape
        nota_html = escape(nota).replace("\n", "<br/>")
        bloque_nota = [
            Paragraph("Notas / Observaciones", st["Sec"]),
            Paragraph(nota_html, st["Sm"]),
            Spacer(1, 8),
        ]
        story.append(KeepTogether(bloque_nota))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRIS, spaceAfter=6))
    story.append(Paragraph("Documento generado por LC Lab. Conserve este comprobante.", st["Cen"]))
    story.append(Paragraph(f"Generado el {ahora_local().strftime('%d/%m/%Y %H:%M:%S')}", st["Cen"]))
    doc.build(story)
    return str(path)


def generar_pdf_milab(detalles, sucursal, desde, hasta):
    """PDF MILAB: estudios cobrados y total de insumos por paciente."""
    from xml.sax.saxutils import escape

    ts = ahora_local().strftime("%Y%m%d_%H%M%S")
    path = DOCS_DIR / f"MILAB_{desde}_{hasta}_{ts}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=1.2*cm,
                            leftMargin=1.2*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    st = _styles()
    story = [
        Paragraph("LC LAB", st["Titulo"]),
        Paragraph("REPORTE DE INSUMOS — MILAB", st["Sub"]),
        Paragraph("Sucursal: " + escape(str(sucursal)), st["Cen"]),
        Paragraph("Periodo: " + escape(str(desde)) + " al " + escape(str(hasta)), st["Cen"]),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=1.5, color=AZUL, spaceAfter=8),
    ]

    pacientes = {}
    for r in detalles:
        folio = str(r["folio_paciente"] or "")
        nombre = str(r["paciente"] or "Paciente sin nombre")
        fecha_atencion = str(r.get("fecha_hora") or "")[:10]
        clave = (fecha_atencion, folio, nombre)
        if clave not in pacientes:
            pacientes[clave] = {
                "total": 0.0, "estudios": [],
                "fecha_atencion": fecha_atencion,
                "fecha_nacimiento": r.get("fecha_nacimiento"),
                "edad": r.get("edad"), "telefono": r.get("telefono")
            }
        pacientes[clave]["total"] += float(r["costo_total"] or 0)
        estudio = str(r["estudio"] or "").strip()
        if estudio and estudio not in pacientes[clave]["estudios"]:
            pacientes[clave]["estudios"].append(estudio)

    data = [[Paragraph("<b>Fecha atención</b>", st["Cen"]),
             Paragraph("<b>Paciente</b>", st["Cen"]),
             Paragraph("<b>Fecha nacimiento</b>", st["Cen"]),
             Paragraph("<b>Edad</b>", st["Cen"]),
             Paragraph("<b>Celular</b>", st["Cen"]),
             Paragraph("<b>Estudios cobrados</b>", st["Cen"]),
             Paragraph("<b>Total de insumos</b>", st["Cen"])]]
    total_general = 0.0
    for (fecha_atencion, folio, nombre), info in sorted(pacientes.items(), key=lambda x: (x[0][0], x[0][2].casefold())):
        nombre_html = escape(nombre)
        if folio:
            nombre_html += "<br/><font size='8'>Folio: " + escape(folio) + "</font>"
        estudios_html = "<br/>".join(escape(x) for x in info["estudios"]) or "Sin estudios registrados"
        data.append([Paragraph(escape(fecha_atencion or "—"), st["Sm"]),
                     Paragraph(nombre_html, st["Sm"]),
                     Paragraph(escape(str(info.get("fecha_nacimiento") or "—")), st["Sm"]),
                     Paragraph(escape(str(info.get("edad") or "—")), st["Cen"]),
                     Paragraph(escape(str(info.get("telefono") or "—")), st["Sm"]),
                     Paragraph(estudios_html, st["Sm"]),
                     Paragraph(f"MXN {info['total']:,.2f}", st["Der"])])
        total_general += info["total"]

    if not pacientes:
        data.append([Paragraph("Sin pacientes registrados en el periodo seleccionado.", st["Sm"]), "", "", "", "", "", ""])
    data.append([Paragraph("<b>TOTAL GENERAL</b>", st["Sm"]), "", "", "", "",
                 "", Paragraph(f"<b>MXN {total_general:,.2f}</b>", st["Der"])])

    tabla = Table(data, repeatRows=1, colWidths=[2.0*cm, 3.5*cm, 2.3*cm, 1.0*cm, 2.2*cm, 5.0*cm, 2.4*cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aab7b8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, AZUL_CLARO]),
        ("BACKGROUND", (0, -1), (-1, -1), AZUL_CLARO),
        ("BOX", (0, -1), (-1, -1), 0.8, AZUL),
        ("SPAN", (0, -1), (5, -1)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([
        tabla, Spacer(1, 12),
        Paragraph("Incluye el nombre de los estudios cobrados y el total de insumos por paciente, con el total general al final. No muestra precios de venta ni cobros individuales.", st["Cen"]),
        Paragraph("Generado el " + ahora_local().strftime("%d/%m/%Y %H:%M:%S"), st["Cen"]),
    ])
    doc.build(story)
    return str(path)


def generar_pdf_reporte_lc(detalles, sucursal, desde, hasta):
    """Reporte general de ventas LC Lab para imprimir o guardar como PDF."""
    from xml.sax.saxutils import escape

    ts = ahora_local().strftime("%Y%m%d_%H%M%S")
    path = DOCS_DIR / f"LC_Lab_{desde}_{hasta}_{ts}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=1.5*cm,
                            leftMargin=1.5*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    st = _styles()
    total_ventas = sum(float(r["total"] or 0) for r in detalles)
    total_cobrado = sum(float(r["monto_recibido"] or 0) for r in detalles)
    total_pendiente = sum(max(0.0, float(r["total"] or 0) - float(r["monto_recibido"] or 0)) for r in detalles)
    total_descuentos = sum(float(r.get("descuento_monto", 0) or 0) for r in detalles)
    story = [
        Paragraph("LC LAB", st["Titulo"]),
        Paragraph("REPORTE DE VENTAS", st["Sub"]),
        Paragraph("Sucursal: " + escape(str(sucursal)), st["Cen"]),
        Paragraph("Periodo: " + escape(str(desde)) + " al " + escape(str(hasta)), st["Cen"]),
        Spacer(1, 8), HRFlowable(width="100%", thickness=1.5, color=AZUL, spaceAfter=8),
    ]
    data = [[Paragraph("<b>Fecha atención</b>", st["Cen"]),
             Paragraph("<b>Folio</b>", st["Cen"]),
             Paragraph("<b>Paciente / estudios realizados</b>", st["Cen"]),
             Paragraph("<b>Fecha y hora</b>", st["Cen"]),
             Paragraph("<b>F. nacimiento</b>", st["Cen"]),
             Paragraph("<b>Edad</b>", st["Cen"]),
             Paragraph("<b>Celular</b>", st["Cen"]),
             Paragraph("<b>Total</b>", st["Cen"]),
             Paragraph("<b>Descuento</b>", st["Cen"]),
             Paragraph("<b>Cobrado</b>", st["Cen"]),
             Paragraph("<b>Estado</b>", st["Cen"])]]
    for r in detalles:
        fecha = str(r["fecha_hora"] or "")[:16].replace("T", " ")
        descuento = float(r.get("descuento_monto", 0) or 0)
        estudios = r.get("estudios") or []
        estudios_html = "<br/><font size='8' color='#566573'>Estudios realizados: " + escape("; ".join(str(x) for x in estudios)) + "</font>" if estudios else "<br/><font size='8' color='#566573'>Estudios realizados: sin detalle registrado</font>"
        fecha_atencion = fecha[:10] if fecha else "—"
        data.append([
            Paragraph(escape(fecha_atencion), st["Sm"]),
            Paragraph(escape(str(r["folio"] or "")), st["Sm"]),
            Paragraph(escape(str(r.get("paciente") or "—")) + estudios_html, st["Sm"]),
            Paragraph(escape(fecha), st["Sm"]),
            Paragraph(escape(str(r.get("fecha_nacimiento") or "—")), st["Sm"]),
            Paragraph(escape(str(r.get("edad") or "—")), st["Cen"]),
            Paragraph(escape(str(r.get("telefono") or "—")), st["Sm"]),
            Paragraph(f"${float(r['total'] or 0):,.2f}", st["Der"]),
            Paragraph(f"${descuento:,.2f}", st["Der"]),
            Paragraph(f"${float(r['monto_recibido'] or 0):,.2f}", st["Der"]),
            Paragraph(escape(str(r["estado_pago"] or "")), st["Sm"]),
        ])
    if not detalles:
        data.append([Paragraph("Sin operaciones confirmadas en el periodo.", st["Sm"]), "", "", "", "", "", "", "", "", "", ""])
    data.append([Paragraph("<b>TOTALES</b>", st["Sm"]), "", "", "", "", "", "",
                 Paragraph(f"<b>${total_ventas:,.2f}</b>", st["Der"]),
                 Paragraph(f"<b>${total_descuentos:,.2f}</b>", st["Der"]),
                 Paragraph(f"<b>${total_cobrado:,.2f}</b>", st["Der"]),
                 ""])
    tabla = Table(data, repeatRows=1, colWidths=[1.4*cm, 1.2*cm, 3.0*cm, 1.8*cm, 1.7*cm, 0.8*cm, 1.7*cm, 1.5*cm, 1.7*cm, 1.7*cm, 1.0*cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aab7b8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, AZUL_CLARO]),
        ("BACKGROUND", (0, -1), (-1, -1), AZUL_CLARO), ("SPAN", (0, -1), (1, -1)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([
        tabla, Spacer(1, 10),
        Paragraph(f"Total pendiente: <b>${total_pendiente:,.2f}</b>", st["Der"]),
        Paragraph("Este reporte incluye solo operaciones confirmadas, activas y no canceladas.", st["Cen"]),
        Paragraph("Generado el " + ahora_local().strftime("%d/%m/%Y %H:%M:%S"), st["Cen"]),
    ])
    doc.build(story)
    return str(path)
