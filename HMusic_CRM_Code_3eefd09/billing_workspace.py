"""Owner billing navigation; existing endpoints retain payment authorization."""
from html import escape
from family_billing import ensure_schema


def billing_workspace_html(cursor):
    ensure_schema(cursor)
    cursor.execute("""SELECT DISTINCT p.id,p.parent_name,p.email,COALESCE(p.phone,'') FROM parent_profiles p
        WHERE COALESCE(p.active,1)=1 AND (
          EXISTS (SELECT 1 FROM invoice_allocations a JOIN invoices i ON i.id=a.invoice_id
            WHERE a.parent_id=p.id AND a.status IN ('unpaid','failed')
            AND i.status NOT IN ('paid','cancelled','canceled','void','waived','pending_owner_approval'))
          OR EXISTS (SELECT 1 FROM parent_students ps JOIN invoices i ON i.student_name=ps.student_name
            WHERE ps.parent_id=p.id AND COALESCE(ps.active,1)=1
            AND i.status NOT IN ('paid','cancelled','canceled','void','waived','pending_owner_approval')))
        ORDER BY p.parent_name,p.id""")
    options=''.join(f'<option value="{int(i)}">{escape(str(n or "Parent"))} · {escape(str(e or ""))} · {escape(str(phone))}</option>' for i,n,e,phone in cursor.fetchall())
    cursor.execute("""SELECT f.id,p.parent_name,f.total_cents,f.status,f.method
        FROM family_payments f JOIN parent_profiles p ON p.id=f.parent_id
        ORDER BY f.id DESC LIMIT 20""")
    rows=''
    for i,n,amount,status,method in cursor.fetchall():
        share=f'<a class="button" data-billing-title="Send combined invoice by SMS" href="/family_payment/{int(i)}/share">Payment link / SMS</a>' if method=='Stripe ACH' and status in ('creating','processing') else ''
        rows+=f'<tr><td>#{int(i)}</td><td>{escape(str(n or "Parent"))}</td><td>${amount/100:,.2f}</td><td>{escape(str(status))}</td><td>{escape(str(method))}</td><td><a class="button" href="/family_payment/{int(i)}">Review</a> {share}</td></tr>'
    return f'''<section class="billing-tools" aria-label="Family billing">
      <div class="billing-tools-heading"><div><h2>Combined family invoices</h2><p>Select a payer to combine invoices. Review existing bills, generate payment links and send SMS here.</p></div>
      <button class="button" id="refresh-billing" type="button">Refresh billing</button></div>
      <label for="billing-family-search">Search parents</label>
      <input id="billing-family-search" type="search" placeholder="Type parent name, email or phone" autocomplete="off" aria-controls="billing-family" style="padding:10px;border:1px solid #d0d5dd;border-radius:8px;width:min(100%,520px);box-sizing:border-box;margin:8px 0 12px;font:inherit">
      <span id="billing-family-count" role="status" aria-live="polite"></span>
      <form id="combine-family-form"><label for="billing-family">Family / payer</label>
      <select id="billing-family" required><option value="">Choose a family…</option>{options}</select>
      <button class="button primary" type="submit">Combine family invoices</button></form>
      <details {'open' if rows else ''}><summary>Recent combined bills</summary><div class="table-wrap"><table><tr><th>Bill</th><th>Payer</th><th>Total</th><th>Status</th><th>Method</th><th>Actions</th></tr>{rows or '<tr><td colspan="6">No combined bills yet.</td></tr>'}</table></div></details>
    </section>
    <dialog id="billing-task" aria-labelledby="billing-task-title"><div class="billing-task-header"><h2 id="billing-task-title">Billing</h2><button class="button" id="close-billing-task" type="button">Close & refresh invoices</button></div>
    <p id="billing-loading" role="status">Loading billing…</p><iframe id="billing-task-frame" title="Billing task" src="about:blank"></iframe></dialog>
    <link rel="stylesheet" href="/static/billing_workspace.css"><script src="/static/billing_workspace.js" defer></script>'''
