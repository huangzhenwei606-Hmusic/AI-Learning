"""Read-only, guardian-scoped billing downloads. No settlement or credit mutations."""
from io import BytesIO
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from html import escape

from flask import abort, make_response, redirect, session, request

LOGO = Path(__file__).parent / 'static' / 'hmusic-icon.png'


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def document_links(base, paid=False):
    links = f'<a class="billing-download" href="{escape(base)}/invoice.pdf?view=1">Download Invoice</a>'
    if paid:
        links += f'<a class="billing-download receipt-download" href="{escape(base)}/receipt.pdf?view=1">Download Receipt</a>'
    else:
        links += '<small class="receipt-help">Receipt available after payment is confirmed.</small>'
    return '<div class="billing-downloads">' + links + '</div>'


def invoice_document(cur, invoice_id, parent_id):
    cur.execute('''SELECT i.id,i.student_name,i.charge_lessons,i.amount,i.status,i.created_at,
        i.due_date,i.coverage_title,i.coverage_class,i.coverage_start,i.coverage_note,
        e.course_type_name,e.teacher_name,e.duration,
        ia.id,ia.amount,ia.status,ia.payment_method,ia.paid_at,pp.parent_name
        FROM invoices i LEFT JOIN enrollments e ON e.id=i.enrollment_id
        JOIN invoice_allocations ia ON ia.invoice_id=i.id AND ia.parent_id=?
        JOIN parent_profiles pp ON pp.id=ia.parent_id WHERE i.id=?''', (parent_id,invoice_id))
    r = cur.fetchone()
    if not r or r[4] in ('pending_owner_approval','draft','void','waived','cancelled','canceled'):
        abort(404)
    line = dict(invoice_id=r[0],student=r[1],lessons=r[2],amount=money(r[15]),
                course=r[8] or r[11] or '',teacher=r[12] or '',duration=r[13],
                coverage=r[7] or '',start=r[9] or '',note=r[10] or '')
    # A split payer sees only their assigned amount, never another guardian's details.
    partial = money(r[15]) != money(r[3])
    doc = dict(number=f'I-{r[0]}-A{r[14]}',title=f'Invoice #{r[0]}',payer=r[19],
        issued=r[5],due=r[6],status=r[16],paid=r[16]=='paid',paid_at=r[18],method=r[17],
        total=money(r[15]),lines=[line],share=partial,receipt_number=f'R-I{r[0]}-A{r[14]}')

    # Fees are separate from tuition and must appear in the receipt across all entrypoints.
    cur.execute('PRAGMA table_info(quick_payment_links)')
    if cur.fetchall() and doc['paid']:
        cur.execute("SELECT fee_cents FROM quick_payment_links WHERE allocation_id=? AND status='paid' AND method='card' ORDER BY attempt_started DESC LIMIT 1",(r[14],))
        fee=cur.fetchone()
        if fee and fee[0]:
            amount=money(Decimal(fee[0])/100)
            doc['lines'].append(dict(invoice_id=r[0],student='Credit card surcharge',lessons=0,amount=amount,course='',teacher=''))
            doc['total']+=amount
    return doc


def family_document(cur, batch_id):
    cur.execute('''SELECT fp.id,pp.parent_name,fp.created_at,fp.status,fp.paid_at,
        fp.method,fp.total_cents FROM family_payments fp JOIN parent_profiles pp
        ON pp.id=fp.parent_id WHERE fp.id=?''',(batch_id,))
    r=cur.fetchone()
    if not r or r[3]=='cancelled': abort(404)
    cur.execute('''SELECT fi.invoice_id,fi.student_name,fi.lessons,fi.amount_cents,
        fi.course_name,fi.teacher_name,i.coverage_title,i.coverage_start,i.coverage_note,
        ia.paid_at,ia.status,e.duration FROM family_payment_items fi JOIN invoices i ON i.id=fi.invoice_id
        LEFT JOIN enrollments e ON e.id=i.enrollment_id
        JOIN invoice_allocations ia ON ia.id=fi.allocation_id
        WHERE fi.family_payment_id=? ORDER BY fi.invoice_id,fi.allocation_id''',(batch_id,))
    rows=cur.fetchall()
    if not rows or sum(x[3] for x in rows)!=r[6]: abort(409)
    paid=r[3]=='paid' and all(x[10]=='paid' for x in rows)
    dates=[str(x[9]) for x in rows if x[9]]
    return dict(number=f'F-{r[0]}',title=f'Family invoice #{r[0]}',payer=r[1],issued=r[2],due='',
        status=r[3],paid=paid,paid_at=max(dates) if dates else r[4],method=r[5],
        total=money(Decimal(r[6])/100),share=True,receipt_number=f'R-F{r[0]}',
        lines=[dict(invoice_id=x[0],student=x[1],lessons=x[2],amount=money(Decimal(x[3])/100),
                    course=x[4] or '',teacher=x[5] or '',coverage=x[6] or '',start=x[7] or '',note=x[8] or '',duration=x[11]) for x in rows])


def build_pdf(doc, kind):
    if kind not in ('invoice','receipt'): abort(404)
    if kind=='receipt' and not doc['paid']: abort(409, 'Receipt is available only after payment is confirmed.')
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    if 'STSong-Light' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    out=BytesIO()
    pdf=SimpleDocTemplate(out,pagesize=(612,792),leftMargin=44,rightMargin=44,topMargin=35,bottomMargin=44,
                         title=f'{kind.title()} {doc["number"]}',author='H-Music')
    style=ParagraphStyle('body',fontName='Helvetica',fontSize=9,leading=14,textColor=HexColor('#172033'),wordWrap='CJK')
    def p(text,size=9,bold=False):
        text=str(text or '')
        font='STSong-Light' if any(ord(c)>0x2ff for c in text) else ('Helvetica-Bold' if bold else 'Helvetica')
        return Paragraph(escape(text).replace('\n','<br/>'),ParagraphStyle('p',parent=style,fontName=font,fontSize=size,leading=size*1.45))
    class BrandLogo(Flowable):
        def __init__(self):
            super().__init__();self.width=42;self.height=42
        def draw(self):
            c=self.canv;c.saveState();clip=c.beginPath();clip.roundRect(0,0,42,42,7);c.clipPath(clip,stroke=0)
            c.drawImage(str(LOGO),-25,-25,width=92,height=92,mask='auto');c.restoreState()
    story=[BrandLogo(),Spacer(1,16),p(kind.upper(),23,True),Spacer(1,7),
           p(doc['receipt_number'] if kind=='receipt' else doc['title'],11,True),Spacer(1,10)]
    state='Paid' if doc['paid'] else str(doc['status'] or 'unpaid').replace('_',' ').title()
    for text in [doc['title'] if kind=='receipt' else '',f'Status: {state}',f'Issued: {doc["issued"] or "Not recorded"}',
                 f'Payment due: {doc["due"]}' if doc.get('due') else '',
                 f'Paid: {doc["paid_at"] or "Date not recorded"}' if doc['paid'] else '',
                 f'Billed to: {doc["payer"] or "Guardian"}']:
        if text:story.append(p(text))
    if doc.get('share'):story.extend([Spacer(1,6),p('Amounts shown cover this payer\'s assigned share. Lesson quantities describe each course package.')])
    story.append(Spacer(1,18))
    data=[[p('Student / Course',9,True),p('Lessons',9,True),p('Amount',9,True)]]
    for line in doc['lines']:
        course=line['course'] + (f' | {float(line["duration"]):g} min' if line.get('duration') else '')
        texts=[line['student'],f'Invoice #{line["invoice_id"]}',course,line.get('teacher','')]
        detail=[p(t,9,i==0) for i,t in enumerate(texts) if t]
        for label,key in [('Coverage','coverage'),('From','start'),('Course details','note')]:
            if line.get(key):detail.append(p(f'{label}: {line[key]}',8))
        data.append([detail,p(f'{float(line["lessons"] or 0):g}'),p(f'${line["amount"]:,.2f}')])
    table=Table(data,colWidths=[364,60,100],repeatRows=1,splitInRow=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#f1f5f9')),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),
        ('BOTTOMPADDING',(0,0),(-1,-1),10),('LINEBELOW',(0,0),(-1,-1),.4,HexColor('#dce3ec'))]))
    story.extend([table,Spacer(1,14),p(f'{"Total paid" if kind=="receipt" else "Invoice total"}: ${doc["total"]:,.2f}',13,True)])
    if doc['paid']:story.extend([Spacer(1,10),p(f'Payment method: {doc["method"] or "Not recorded"}')])
    story.extend([Spacer(1,20),p('Thank you for your payment.' if kind=='receipt' else 'Keep this invoice for your records.',9,True)])
    def footer(canvas, document):
        canvas.setFont('Helvetica',8);canvas.setFillColor(HexColor('#64748b'))
        canvas.drawString(44,25,doc['number']);canvas.drawRightString(568,25,f'Page {document.page}')
    pdf.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()


def pdf_response(doc,kind):
    if kind not in ('invoice','receipt'):abort(404)
    if kind=='receipt' and not doc['paid']:abort(409, 'Receipt is available only after payment is confirmed.')
    filename=f'H-Music-{kind}-{doc["number"]}.pdf'
    if request.args.get('view')=='1':
        # Keep app navigation outside the PDF viewer; never trust a return URL parameter.
        base=request.path.rsplit('/',1)[0]
        url=escape(request.path)
        response=make_response(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
            <title>{kind.title()} preview</title><link rel="stylesheet" href="/static/billing_documents.css?v=2">
            <script src="/static/billing_documents.js?v=2" defer></script></head>
            <body class="billing-document-view"><header class="document-toolbar">
                <a class="document-back" href="{escape(base)}">← Back to invoice</a>
                <span class="document-heading">{kind.title()}</span>
                <button type="button" class="document-save" data-pdf-url="{url}" data-filename="{escape(filename)}">Save PDF</button>
            </header><p class="document-status" role="status" aria-live="polite">Use Save PDF to save or share. Back to invoice returns to your bill.</p>
            <iframe class="document-frame" src="{url}?inline=1" title="{kind.title()} PDF preview"></iframe>
            <p class="document-fallback">Preview unavailable? Use Save PDF above.</p></body></html>''')
    else:
        response=make_response(build_pdf(doc,kind))
        response.headers['Content-Type']='application/pdf'
        disposition='inline' if request.args.get('inline')=='1' else 'attachment'
        response.headers['Content-Disposition']=f'{disposition}; filename="{filename}"'
    response.headers['Cache-Control']='private, no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Robots-Tag']='noindex, nofollow'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


def install_billing_documents(app,api):
    @app.route('/parent_invoice/<int:invoice_id>/<kind>.pdf')
    def parent_billing_document(invoice_id,kind):
        if not api['require_parent']():return redirect('/parent_login')
        api['ensure_guardian_billing_schema']()
        conn=api['sqlite3'].connect('hmusic.db')
        try:
            cur=conn.cursor()
            cur.execute('SELECT student_name FROM invoices WHERE id=?',(invoice_id,))
            row=cur.fetchone();pid=session.get('parent_id')
            if not row:abort(404)
            if not api['parent_can_access_student'](pid,row[0]) or not api['parent_has_student_permission'](pid,row[0],'view_billing'):abort(403)
            return pdf_response(invoice_document(cur,invoice_id,pid),kind)
        finally:conn.close()


def billing_records(cur,parent_id,api):
    from family_billing import ensure_schema
    ensure_schema(cur)
    cur.execute('''SELECT fp.id,fp.status,fp.total_cents,fp.method FROM family_payments fp
        WHERE fp.parent_id=? AND fp.status!='cancelled' ORDER BY fp.id DESC''',(parent_id,))
    cards=[];grouped=set()
    def permitted(student):
        return api['parent_can_access_student'](parent_id,student) and api['parent_has_student_permission'](parent_id,student,'view_billing')
    for bid,status,total,method in cur.fetchall():
        cur.execute('SELECT invoice_id,student_name FROM family_payment_items WHERE family_payment_id=?',(bid,))
        items=cur.fetchall()
        if not items or not all(permitted(s) for _,s in items):continue
        grouped.update(i for i,_ in items)
        is_paid=family_document(cur,bid)['paid']
        names=', '.join(dict.fromkeys(s for _,s in items))
        label='Paid' if is_paid else 'Payment processing' if status in ('submitted','processing') else 'Unpaid'
        cards.append(f'<article class="billing-record" data-paid="{str(is_paid).lower()}"><h3>Family invoice #{bid} · {label}</h3><p>{escape(names)}</p><p class="total">${total/100:,.2f}</p><p>{escape(method or "")}</p><a href="/family_payment/{bid}">View details</a>{document_links(f"/family_payment/{bid}",is_paid)}</article>')
    cur.execute('''SELECT i.id,i.student_name,ia.amount,ia.status,ia.payment_method,ia.paid_at
        FROM invoices i JOIN invoice_allocations ia ON ia.invoice_id=i.id WHERE ia.parent_id=?
        AND COALESCE(i.status,'') NOT IN ('pending_owner_approval','draft','void','waived','cancelled','canceled')
        ORDER BY i.id DESC''',(parent_id,))
    for iid,student,amount,status,method,paid_at in cur.fetchall():
        if iid in grouped or not permitted(student):continue
        label='Paid' if status=='paid' else 'Payment processing' if status=='processing' else str(status or 'unpaid').replace('_',' ').title()
        paid_info=f'Paid {paid_at or "date not recorded"} · {method or "method not recorded"}' if status=='paid' else ''
        cards.append(f'<article class="billing-record" data-paid="{str(status=="paid").lower()}"><h3>Invoice #{iid} · {escape(label)}</h3><p>{escape(student)}</p><p class="total">${float(amount or 0):,.2f}</p><p>{escape(paid_info)}</p><a href="/parent_invoice/{iid}">View details</a>{document_links(f"/parent_invoice/{iid}",status=="paid")}</article>')
    return '<h2>Invoices & receipts</h2><div class="billing-tabs" role="group" aria-label="Filter invoices">' + ''.join(f'<button type="button" data-filter="{f}" aria-pressed="{str(f=="all").lower()}">{f.title()}</button>' for f in ('all','unpaid','paid')) + '</div><section id="billing-records">'+(''.join(cards) or '<p>No invoices yet.</p>')+'</section><script>document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll("[data-filter]").forEach(x=>x.setAttribute("aria-pressed",String(x===b)));document.querySelectorAll(".billing-record").forEach(c=>c.hidden=b.dataset.filter!=="all" && (c.dataset.paid==="true")!==(b.dataset.filter==="paid"));}));</script>'
