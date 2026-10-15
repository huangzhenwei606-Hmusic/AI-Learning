/* Shared by the owner calendar and teacher portal, including its mobile wrapper. */
(() => {
  'use strict';
  if (window.HMusicLessonComments) return;
  const bubble = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 10 10 0 0 1-4-.8L3 21l1.6-5.2a8.8 8.8 0 0 1-1.6-4.9A8.6 8.6 0 0 1 12 3a8.6 8.6 0 0 1 9 8.5Z"/></svg>';
  const cards = () => [...document.querySelectorAll('.ev[data-id],.calendar-event[data-id]')];
  let currentId = null, thread = null, mode = null, generation = 0, trigger = null, busy = false, syncing = false, loadingThread = false;
  const summaries = new Map(), drafts = new Map(), seenEvents = new Map();
  const node = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  const drawer = node('aside','lc-drawer');
  drawer.hidden = true; drawer.setAttribute('role','dialog'); drawer.setAttribute('aria-modal','true'); drawer.setAttribute('aria-labelledby','lc-heading'); drawer.tabIndex = -1;
  // All dynamic user content is assigned with textContent, never HTML.
  drawer.innerHTML = `<div class="lc-head"><div class="lc-heading"><h2 id="lc-heading">${bubble}Lesson comments</h2><button class="lc-close" type="button" aria-label="Close comments">×</button></div><div class="lc-student"></div><div class="lc-context"></div><div class="lc-privacy"><span>Staff only</span><span>Only this lesson</span></div></div><div class="lc-list" aria-label="Conversation"></div><form class="lc-compose"><div class="lc-error" role="alert"></div><div class="lc-mode" hidden><span></span><button type="button">Cancel</button></div><label class="lc-input-label" for="lc-input" hidden>Comment</label><textarea id="lc-input" aria-label="Add a comment" placeholder="Add a comment…" maxlength="5000" rows="3"></textarea><div class="lc-compose-bottom"><span>Visible to staff only</span><button class="lc-post" type="submit" disabled>Post</button></div></form>`;
  const scrim = node('div','lc-scrim'); scrim.hidden = true;
  document.body.append(scrim,drawer);
  const list = drawer.querySelector('.lc-list'), input = drawer.querySelector('textarea'), post = drawer.querySelector('.lc-post'), error = drawer.querySelector('.lc-error'), modeBox = drawer.querySelector('.lc-mode');
  async function api(path, method = 'GET', body) {
    const response = await fetch('/api/lesson-comments' + path, {method, credentials:'same-origin', cache:'no-store', headers:{'Accept':'application/json', ...(body === undefined ? {} : {'Content-Type':'application/json','X-CSRFToken':window.HMUSIC_CSRF_TOKEN || document.querySelector('meta[name="csrf-token"]')?.content || ''})}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    let data; try { data = await response.json(); } catch (_) { throw new Error('Session expired or server unavailable. Refresh and try again.'); }
    if (!response.ok || !data.ok) throw new Error(data.error || 'Unable to save comments. Please try again.');
    return data;
  }
  function paintBadges() {
    for (const card of cards()) {
      const state = summaries.get(String(card.dataset.id));
      let badge = card.querySelector('.lc-icon');
      if (!state?.count) { badge?.remove(); continue; }
      if (!badge) {
        const title = card.querySelector('.ev-name,.event-student'); if (!title) continue;
        let line = title.parentElement;
        if (!line.classList.contains('lc-title-line')) { line = node('div','lc-title-line'); title.before(line); line.append(title); }
        badge = node('button','lc-icon'); badge.type = 'button'; badge.draggable = false; badge.innerHTML = bubble;
        badge.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); open(card.dataset.id,badge); });
        badge.addEventListener('mousedown', e => e.stopPropagation());
        badge.addEventListener('dragstart', e => { e.preventDefault(); e.stopPropagation(); });
        line.append(badge);
      }
      badge.classList.toggle('lc-unread',state.unread);
      const label = `${state.count} comment${state.count === 1 ? '' : 's'}${state.unread ? ' · Unread' : ''}`;
      badge.title = label; badge.setAttribute('aria-label',label);
    }
  }
  async function sync() {
    if (syncing || document.hidden) return;
    syncing = true;
    try {
      const ids = [...new Set(cards().map(card => Number(card.dataset.id)).filter(id => id > 0))];
      for (let start = 0; start < ids.length; start += 150) {
        const batch = ids.slice(start,start + 150);
        const data = await api('/summary?ids=' + batch.join(','));
        batch.forEach(id=>summaries.set(String(id),{count:0,unread:false}));
        Object.entries(data.lessons).forEach(([id,state]) => summaries.set(id,state));
      }
      paintBadges();
      if (currentId && !loadingThread && !busy) await loadThread(false);
    } catch (_) { /* Background sync must not interrupt attendance or discard drafts. */ }
    finally { syncing = false; }
  }
  function setMode(value) {
    mode = value; modeBox.hidden = !value;
    modeBox.querySelector('span').textContent = value ? (value.edit ? 'Edit your comment' : 'Reply to ' + value.author) : '';
    post.textContent = value?.edit ? 'Save' : 'Post';
    input.setAttribute('aria-label',value?.edit ? 'Edit your comment' : value ? 'Write a reply' : 'Add a comment');
    input.placeholder = value ? 'Write your reply…' : 'Add a comment…';
    if (value?.edit) input.placeholder = 'Edit your comment…';
    updatePost();
  }
  function updatePost() { post.disabled = busy || !thread || !input.value.trim(); }
  function renderThread(data, scrollBottom) {
    const oldScroll = list.scrollTop;
    list.replaceChildren();
    drawer.querySelector('.lc-student').textContent = data.lesson.student;
    drawer.querySelector('.lc-context').textContent = [data.lesson.date,data.lesson.time,data.lesson.teacher].filter(Boolean).join(' · ');
    if (!data.comments.length) list.append(node('div','lc-empty','No comments yet.\nAdd a note for this lesson’s teacher and owner.'));
    const roots = data.comments.filter(c => !c.parent_id);
    const replies = new Map();
    data.comments.filter(c => c.parent_id).forEach(c => { if (!replies.has(c.parent_id)) replies.set(c.parent_id,[]); replies.get(c.parent_id).push(c); });
    function entry(c,isReply) {
      const row = node('article','lc-comment' + (isReply ? ' lc-reply' : ''));
      const initials = c.author.split(/\s+/).filter(Boolean).map(v=>v[0]).slice(0,2).join('').toUpperCase();
      row.append(node('span','lc-avatar',initials));
      const content = node('div','lc-comment-content'), meta = node('div','lc-comment-meta');
      meta.append(node('strong','',c.author));
      const stamp = node('time'); stamp.dateTime = c.created_at;
      stamp.textContent = new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(c.created_at)) + (c.edited_at ? ' · edited' : '');
      meta.append(stamp); content.append(meta,node('p','lc-comment-body',c.body));
      const actions = node('div','lc-comment-actions'), reply = node('button','','Reply'); reply.type = 'button';
      reply.onclick = () => { if (busy) return; if (input.value.trim() && !window.confirm('Replace your current draft with this reply?')) return; input.value=''; setMode({parent_id:c.parent_id || c.id,author:c.author}); input.focus(); };
      actions.append(reply);
      if (c.can_edit) { const edit = node('button','','Edit'); edit.type='button'; edit.onclick=()=>{ if (busy) return; if (input.value.trim() && !window.confirm('Replace your current draft to edit this comment?')) return; setMode({edit:c.id,revision:c.revision,author:c.author}); input.value=c.body; updatePost(); input.focus(); }; actions.append(edit); }
      content.append(actions); row.append(content); list.append(row);
    }
    roots.forEach(root => { entry(root,false); (replies.get(root.id) || []).forEach(reply=>entry(reply,true)); });
    list.scrollTop = scrollBottom ? list.scrollHeight : oldScroll;
  }
  async function loadThread(scrollBottom = false) {
    if (!currentId || loadingThread) return;
    const id = currentId, token = generation; loadingThread = true;
    try {
      const data = await api('/' + id);
      if (token !== generation || id !== currentId) return;
      const changed = !thread || data.event_id !== thread.event_id;
      thread = data;
      if (changed || scrollBottom) renderThread(data,scrollBottom);
      updatePost();
      if (seenEvents.get(id) !== data.event_id) {
        await api('/' + id + '/read','POST',{event_id:data.event_id});
        seenEvents.set(id,data.event_id);
      }
      if (token !== generation || id !== currentId) return;
      summaries.set(String(id),{count:data.comments.length,unread:false}); paintBadges();
    } catch (e) { if (token === generation) { error.textContent=e.message; if (!thread) list.replaceChildren(node('div','lc-empty','Could not load comments. Close and reopen to retry.')); } }
    finally { loadingThread=false; }
  }
  async function open(id,source) {
    id = Number(id); if (!Number.isInteger(id) || id < 1 || busy) return;
    if (currentId) drafts.set(currentId,{text:input.value,mode});
    const openGeneration = ++generation; currentId=id; thread=null; trigger=source || document.activeElement; error.textContent='';
    const draft = drafts.get(id); input.value=draft?.text || ''; setMode(draft?.mode || null);
    drawer.hidden=false; scrim.hidden=false;
    drawer.querySelector('.lc-student').textContent='Loading…'; drawer.querySelector('.lc-context').textContent=''; list.replaceChildren(node('div','lc-empty','Loading comments…'));
    drawer.querySelector('.lc-close').focus();
    // Requests from a previously opened lesson must finish before starting this one.
    while (loadingThread) await new Promise(resolve=>setTimeout(resolve,40));
    if (openGeneration === generation && currentId === id) await loadThread(true);
  }
  function close() {
    if (busy) return;
    if (currentId) drafts.set(currentId,{text:input.value,mode});
    generation++; currentId=null; thread=null; drawer.hidden=true; scrim.hidden=true;
    if (trigger?.isConnected) trigger.focus();
  }
  drawer.querySelector('.lc-close').onclick=close; scrim.onclick=close;
  modeBox.querySelector('button').onclick=()=>{ input.value=''; setMode(null); input.focus(); };
  input.oninput=updatePost;
  drawer.querySelector('form').onsubmit=async e=>{
    e.preventDefault(); if (busy || !thread || !input.value.trim()) return;
    busy=true; updatePost(); error.textContent=''; const id=currentId, text=input.value;
    try {
      if (mode?.edit) await api('/'+id+'/'+mode.edit,'PATCH',{body:text,revision:mode.revision});
      else await api('/'+id,'POST',{body:text,parent_id:mode?.parent_id || null});
      input.value=''; drafts.delete(id); setMode(null);
      while (loadingThread) await new Promise(resolve=>setTimeout(resolve,40));
      await loadThread(true);
    } catch (e) { error.textContent=e.message; /* Keep text and edit revision for retry. */ }
    finally { busy=false; updatePost(); }
  };
  drawer.addEventListener('keydown',e=>{
    if (e.key==='Escape') { e.stopPropagation(); close(); }
    if (e.key==='Tab') {
      const focusable=[...drawer.querySelectorAll('button,textarea')].filter(el=>!el.disabled && el.getClientRects().length);
      if (e.shiftKey && document.activeElement===focusable[0]) { e.preventDefault(); focusable.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement===focusable.at(-1)) { e.preventDefault(); focusable[0].focus(); }
    }
    if ((e.ctrlKey || e.metaKey) && e.key==='Enter' && !post.disabled) { e.preventDefault(); drawer.querySelector('form').requestSubmit(); }
  });
  window.HMusicLessonComments={open,refresh:sync};
  document.addEventListener('visibilitychange',()=>{ if (!document.hidden) sync(); });
  window.addEventListener('focus',sync);
  // Server-backed polling keeps owner and teacher sessions synchronized without
  // sending comment content to calendar cards or third-party notification systems.
  sync(); setInterval(sync,15000);
})();
