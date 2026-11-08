"""Shared routing checks: an intake row is not necessarily a private trial lead."""

def table_exists(c,name):
    return bool(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def private_trial_block_reason(c,inquiry,own_order_id=None,check_conversion=True):
    if not inquiry:return '咨询记录不存在'
    text=' '.join(str(inquiry.get(k) or '') for k in ('source','program_interest','instrument')).casefold()
    if any(x in text for x in ('group class','group enrollment','group registration','circle piano','circle-piano','团课')):
        return '这是团课报名，请在「团课报名审核」中处理，不能建立私课试听流程。'
    # The canonical relation wins even if someone edits the source/display label.
    if table_exists(c,'group_applications') and c.execute('SELECT id FROM group_applications WHERE inquiry_id=? LIMIT 1',(inquiry['id'],)).fetchone():
        return '该咨询已关联团课报名，请在「团课报名审核」中处理。'
    if check_conversion and (inquiry.get('converted_student_name') or inquiry.get('converted_enrollment_id')):
        return '该咨询已转为正式学生或已有关联报名，不能再次建立试听流程。'
    status=str(inquiry.get('status') or '').strip().casefold()
    trial_status=str(inquiry.get('trial_status') or '').strip().casefold()
    if check_conversion and (status in ('active','active student','enrolled','converted','registered','registration submitted') or trial_status=='registration'):
        return '这是已报名或直接报名记录，不是待安排的私课试听请求。'
    if table_exists(c,'admissions_orders') and c.execute("SELECT id FROM admissions_orders WHERE inquiry_id=? AND id<>? AND status NOT IN ('cancelled','expired','failed') LIMIT 1",(inquiry['id'],own_order_id or '')).fetchone():
        return '该咨询已有报名或付款订单，请核对现有订单，不能重复建立试听流程。'
    return ''
