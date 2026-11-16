(() => {
  'use strict';
  const dialog = document.createElement('dialog');
  dialog.className = 'cpm-dialog';
  dialog.setAttribute('aria-labelledby','cpm-title');
  dialog.innerHTML = `<form><header><h2 id="cpm-title">Message parent</h2><button type="button" class="cpm-close" aria-label="Close parent message">×</button></header><p class="cpm-context"></p><p class="cpm-status" role="status"></p><p class="cpm-error" role="alert"></p><label>To · linked parent<select class="cpm-parent" required></select></label><label>Template<select class="cpm-template"></select></label><label>Message<textarea class="cpm-body" placeholder="Type your message to the parent…" maxlength="10000" required></textarea></label><fieldset><legend>Also notify by</legend><label><input type="checkbox" class="cpm-email"> Email</label><label><input type="checkbox" class="cpm-sms"> Mobile SMS</label></fieldset><p class="cpm-muted">The message is saved in the parent app. Email/SMS is sent only when selected.</p><footer><a class="cpm-thread" hidden>View conversation</a><button class="cpm-send" type="submit">Send to parent</button></footer></form>`;
  document.body.append(dialog);
  const $ = s => dialog.querySelector(s);
  let lessonId, parents=[], busy=false, sent=false, origin, token, lesson, draftTemplate='custom', parentIndex=0;
  function state() { $('.cpm-send').disabled=busy || sent || !parents.length; $('.cpm-close').disabled=busy; $('.cpm-parent').disabled=busy || sent; $('.cpm-body').disabled=busy || sent; $('.cpm-template').disabled=busy || sent;  }
  async function api(body) {
    const r = await fetch('/api/calendar-parent-message/'+lessonId,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json',...(body?{'Content-Type':'application/json','X-CSRFToken':window.HMUSIC_CSRF_TOKEN||''}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const data=await r.json().catch(()=>({error:'Unable to read the response. Check the conversation before retrying.'}));
    if(!r.ok || !data.ok) throw new Error(data.error || 'Unable to send. Check delivery settings and try again.');
    return data;
  }
  HMusicParentTemplates.options.forEach(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;$('.cpm-template').append(option);});
  function applyTemplate() {
    const kind=$('.cpm-template').value, p=parents[Number($('.cpm-parent').value)];
    if(!p || !lesson)return;
    const previous=HMusicParentTemplates.build(draftTemplate,lesson,p);
    if($('.cpm-body').value.trim() && $('.cpm-body').value!==previous && !confirm('Replace your edited message with this template?')) {$('.cpm-template').value=draftTemplate;return;}
    $('.cpm-body').value=HMusicParentTemplates.build(kind,lesson,p);draftTemplate=kind;$('.cpm-body').focus();
  }
  $('.cpm-template').onchange=applyTemplate;
  $('.cpm-parent').onchange=()=>{
    const next=Number($('.cpm-parent').value), old=parents[parentIndex];
    const generated=old && lesson ? HMusicParentTemplates.build(draftTemplate,lesson,old) : '';
    if($('.cpm-body').value.trim() && $('.cpm-body').value!==generated && !confirm('Changing the recipient will clear your edited draft. Continue?')) {$('.cpm-parent').value=parentIndex;return;}
    parentIndex=next;$('.cpm-body').value=HMusicParentTemplates.build(draftTemplate,lesson,parents[next]);
  };
  function close() {if(busy)return;if(!sent && $('.cpm-body').value.trim() && !confirm('Discard this message draft?'))return;dialog.close();origin?.focus();}
  $('.cpm-close').onclick=close;
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  $('form').onsubmit=async e=>{
    e.preventDefault();if(busy || sent)return;
    const p=parents[Number($('.cpm-parent').value)];if(!p)return;
    busy=true;state();$('.cpm-error').textContent='';
    try {
      const channels=[];if($('.cpm-email').checked)channels.push('email');if($('.cpm-sms').checked)channels.push('sms');
      const d=await api({parent_id:p.id,student:p.student,body:$('.cpm-body').value,channels,token});
      sent=true;$('.cpm-status').textContent=d.message;$('.cpm-thread').href=d.thread_url;$('.cpm-thread').hidden=false;$('.cpm-send').textContent='Saved';
    } catch(err) { $('.cpm-error').textContent=err.message; } finally {busy=false;state();}
  };
  async function open(id,trigger) {
    if(dialog.open)return;lessonId=Number(id);token=crypto.randomUUID();origin=trigger;parents=[];parentIndex=0;lesson=null;draftTemplate='custom';$('.cpm-template').value='custom';sent=false;busy=true;
    $('.cpm-parent').replaceChildren();$('.cpm-body').value='';$('.cpm-error').textContent='';$('.cpm-status').textContent='Loading linked parents…';$('.cpm-context').textContent='';$('.cpm-thread').hidden=true;$('.cpm-send').textContent='Send to parent';state();dialog.showModal();
    try {
      const d=await api();parents=d.parents;lesson=d.lesson;
      $('.cpm-context').textContent=[d.lesson.student,d.lesson.date,d.lesson.display_time || d.lesson.time,d.lesson.teacher].filter(Boolean).join(' · ');
      parents.forEach((p,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${p.name} · ${p.student} · ${p.email || p.phone || 'Parent app'}`;$('.cpm-parent').append(o);});
      $('.cpm-email').checked=d.email_ready;$('.cpm-email').disabled=!d.email_ready;$('.cpm-sms').checked=false;$('.cpm-sms').disabled=!d.sms_ready;
      $('.cpm-status').textContent=parents.length?'':'No linked parent. Link a parent in the student profile first.';
      $('.cpm-body').focus();
    } catch(e) {$('.cpm-error').textContent=e.message;} finally {busy=false;state();$('.cpm-body').focus();}
  }
  window.HMusicParentMessage={open};
  function addButtons() {
    document.querySelectorAll('.ev[data-id]').forEach(card=>{
      if(card.querySelector('.cpm-card'))return;
      const title=card.querySelector('.lc-title-line') || card.querySelector('.ev-name')?.parentElement;
      if(!title)return;
      const b=document.createElement('button');b.type='button';b.className='cpm-card';b.textContent='Parent';b.title='Message parent';b.setAttribute('aria-label','Message parent');
      b.onclick=e=>{e.preventDefault();e.stopPropagation();open(card.dataset.id,b);};b.onmousedown=e=>e.stopPropagation();title.append(b);
    });
  }
  addButtons();new MutationObserver(addButtons).observe(document.querySelector('.calendar-grid') || document.body,{childList:true,subtree:true});
})();
