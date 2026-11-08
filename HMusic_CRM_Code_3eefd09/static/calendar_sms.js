(() => {
  'use strict';
  if (window.HMusicCalendarSms) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'calendar-sms-dialog';
  dialog.setAttribute('aria-labelledby', 'csms-title');
  dialog.innerHTML = `<header><div><h2 id="csms-title">SMS lesson reminder</h2><p>Choose a lesson and the parents who should receive its details.</p></div><button type="button" class="csms-close" aria-label="Close SMS reminder">×</button></header>
    <div class="csms-content"><p class="csms-status" role="status"></p><p class="csms-error" role="alert"></p>
    <form><section class="csms-edit"><label for="csms-lesson">Lesson · current calendar filters</label><select id="csms-lesson" required></select><p class="csms-context"></p>
    <fieldset><legend>Send to selected parents</legend><div class="csms-parents"></div></fieldset>
    <label for="csms-note">Additional note · optional</label><textarea id="csms-note" maxlength="400" placeholder="Add a short note to the lesson details"></textarea>
    <p class="csms-muted">Includes student, date, Pacific time, teacher, location and room. Parents with reminders turned off or no valid mobile number cannot be selected.</p></section>
    <section class="csms-review" hidden><h3>Review SMS</h3><div class="csms-previews"></div><p>Confirm the recipients and lesson details before sending. Shared phone numbers receive one message.</p></section>
    <footer><button type="button" class="csms-back" hidden>Back to edit</button><button type="submit" class="csms-submit">Preview SMS</button></footer></form>
    <section class="csms-history"><h3>Recent SMS history</h3><div class="csms-history-list"></div></section></div>`;
  document.body.append(dialog);
  const $ = selector => dialog.querySelector(selector);
  let sid = null, data = null, previews = [], busy = false, reviewing = false, origin = null, generation = 0;
  const node = (tag, text, cls) => {const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el;};
  const error = message => {$('.csms-error').textContent = message || '';};
  async function api(path, body) {
    const response = await fetch('/api/calendar-sms/' + path, {method:body ? 'POST' : 'GET', credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json', ...(body ? {'Content-Type':'application/json','X-CSRFToken':window.HMUSIC_CSRF_TOKEN || ''} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
    const result = await response.json().catch(() => ({ok:false,error:'Session expired or server unavailable. Refresh and try again.'}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Unable to load reminder');
    return result;
  }
  function review(on) {
    reviewing = on; $('.csms-edit').hidden = on; $('.csms-review').hidden = !on; $('.csms-back').hidden = !on;
    $('.csms-submit').textContent = on ? `Send ${previews.length} SMS now` : 'Preview SMS';
  }
  function controls() {
    $('.csms-submit').disabled = busy || !data?.sms_ready;
    $('.csms-back').disabled = busy; $('.csms-close').disabled = busy; $('#csms-lesson').disabled = busy;
  }
  async function loadLesson() {
    const version = ++generation;
    sid = Number($('#csms-lesson').value); data = null; previews = []; review(false); error(''); controls();
    $('.csms-parents').replaceChildren(); $('.csms-history-list').replaceChildren();
    $('.csms-context').textContent = ''; $('.csms-status').textContent = 'Loading lesson…';
    try {
      const result = await api('lesson/' + sid);
      if (version !== generation || !dialog.open) return;
      data = result;
      const l = data.lesson;
      $('.csms-context').textContent = `${l.student} · ${l.date} · ${l.time} · ${l.teacher} · ${l.location} · ${l.room}`;
      for (const p of data.parents) {
        const label = node('label', '', 'csms-parent');
        const check = document.createElement('input'); check.type = 'checkbox'; check.value = p.id; check.disabled = !p.available;
        label.append(check,node('span',`${p.name} · ${p.phone || 'No mobile number'}\n${p.students.join(', ')}${p.reason ? ' · ' + p.reason : ''}`));
        $('.csms-parents').append(label);
      }
      if (!data.parents.length) $('.csms-parents').append(node('p','No linked parents. Link this student to a parent profile first.'));
      if (!data.sms_ready) error('SMS service is not configured. Contact the manager.');
      for (const h of data.history) $('.csms-history-list').append(node('p',`${new Date(h.created_at).toLocaleString()} · ${h.phone} · ${h.status}${h.status === 'accepted' ? ' (provider accepted; handset delivery not confirmed)' : ''}${h.status === 'unconfirmed' || h.status === 'sending' ? ' — ' + (h.detail || 'Outcome unknown') + '; check SMS provider records before sending again' : ''}`));
      if (!data.history.length) $('.csms-history-list').append(node('p','No SMS reminders sent for this lesson.','csms-muted'));
    } catch (e) {if (version === generation) error(e.message);} finally {if (version === generation) {$('.csms-status').textContent = ''; controls();}}
  }
  $('#csms-lesson').onchange = loadLesson;
  $('.csms-back').onclick = () => {review(false); error('');};
  $('form').onsubmit = async event => {
    event.preventDefault(); if (busy || !data) return; error('');
    busy = true; controls();
    try {
      if (!reviewing) {
        const ids = [...dialog.querySelectorAll('.csms-parent input:checked')].map(c => Number(c.value));
        if (!ids.length) throw new Error('Select at least one parent.');
        const result = await api('lesson/' + sid + '/preview', {parent_ids:ids,note:$('#csms-note').value});
        previews = result.previews; $('.csms-previews').replaceChildren();
        for (const p of previews) {
          const card = node('article','','csms-preview'); card.append(node('strong',`${p.name} · ${p.phone}`), node('pre',p.body)); $('.csms-previews').append(card);
        }
        review(true);
      } else {
        let accepted = 0;
        for (const p of previews) {
          $('.csms-status').textContent = `Sending SMS to ${p.name}…`;
          try {
            const result = await api('send/' + p.token, {});
            if (result.status === 'accepted') accepted++;
            else throw new Error((result.detail || 'SMS outcome is not confirmed.') + ' Check provider records before sending again.');
          } catch (e) {
            throw new Error(`${accepted} accepted by the SMS provider. ${p.name}: ${e.message} Previously submitted messages will not be resent when you retry.`);
          }
        }
        await loadLesson();
        $('.csms-status').textContent = `${accepted} SMS accepted by the provider. Delivery to the phone is not yet confirmed.`;
      }
    } catch (e) {error(e.message);} finally {busy = false; controls();}
  };
  function close() {if (!busy) {generation++; dialog.close(); origin?.focus();}}
  $('.csms-close').onclick = close;
  dialog.addEventListener('cancel',event => {event.preventDefault(); close();});
  window.HMusicCalendarSms = {open:async (id, trigger) => {
    if (dialog.open) return;
    origin = trigger || document.activeElement; data = null; busy = false; reviewing = false; previews = []; $('#csms-note').value = ''; error(''); review(false); controls();
    $('.csms-parents').replaceChildren(); $('.csms-context').textContent = ''; $('.csms-history-list').replaceChildren(); $('#csms-lesson').replaceChildren();
    $('.csms-status').textContent = 'Loading lessons…'; dialog.showModal();
    const version = ++generation;
    try {
      if (id) {
        const option = node('option','Selected calendar lesson'); option.value = id; $('#csms-lesson').append(option);
      } else {
        const params = new URLSearchParams(location.search); params.delete('_workspace');
        const result = await api('lessons?' + params);
        if (version !== generation || !dialog.open) return;
        for (const lesson of result.lessons) {const option = node('option',lesson.label); option.value = lesson.id; $('#csms-lesson').append(option);}
        if (!result.lessons.length) throw new Error('No upcoming scheduled lessons in this calendar view. Choose another month or filter.');
        if (result.truncated) error('Showing the first 500 lessons. Use calendar filters to narrow the list.');
      }
      await loadLesson();
      if (id && data) $('#csms-lesson').selectedOptions[0].textContent = `${data.lesson.date} ${data.lesson.time} · ${data.lesson.student}`;
    } catch (e) {error(e.message); $('.csms-status').textContent = '';}
  }};
})();
