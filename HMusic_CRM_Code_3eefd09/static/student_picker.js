/* Shared owner/teacher student search, independent of native datalist support. */
(() => {
  'use strict';
  const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
  const matches = (label, query) => normalize(query).split(' ').every(word => normalize(label).includes(word));
  if (typeof module !== 'undefined' && module.exports) module.exports = {normalize, matches};
  if (typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = '.hmusic-student-results{position:fixed;z-index:2147483647;box-sizing:border-box;max-height:240px;overflow:auto;background:#fff;border:1px solid #cbd5e1;border-radius:8px;box-shadow:0 8px 24px #0002;padding:4px;color:#111827;font:14px system-ui}.hmusic-student-results [role=option]{padding:10px 12px;cursor:pointer;white-space:normal;overflow-wrap:anywhere}.hmusic-student-results [aria-selected=true]{background:#eff6ff;color:#1d4ed8}.hmusic-student-results [role=status]{padding:10px 12px;color:#64748b}';
  document.head.append(style);
  let sequence = 0;
  function bind(input) {
    if (input.dataset.hmusicStudentPicker) return;
    const list = document.getElementById(input.getAttribute('list'));
    if (!list) return;
    input.dataset.hmusicStudentPicker = '1';
    const choices = Array.from(list.options, option => option.value).filter(Boolean);
    input.removeAttribute('list');
    input.autocomplete = 'off';
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    const menu = document.createElement('div');
    menu.className = 'hmusic-student-results';
    menu.id = 'hmusic-student-results-' + (++sequence);
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;
    document.body.append(menu);
    input.setAttribute('aria-controls', menu.id);
    let rows = [], active = -1;
    function close() {
      menu.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      active = -1;
    }
    function position() {
      const rect = input.getBoundingClientRect();
      menu.style.left = Math.max(0, rect.left) + 'px';
      menu.style.width = Math.min(rect.width, window.innerWidth) + 'px';
      const below = window.innerHeight - rect.bottom;
      menu.style.maxHeight = Math.max(80, Math.min(240, below >= 160 ? below - 8 : rect.top - 8)) + 'px';
      menu.style.top = below >= 160 ? rect.bottom + 'px' : 'auto';
      menu.style.bottom = below >= 160 ? 'auto' : (window.innerHeight - rect.top) + 'px';
    }
    function choose(index) {
      if (!rows[index]) return;
      input.value = rows[index].textContent;
      input.dispatchEvent(new Event('input', {bubbles:true}));
      input.dispatchEvent(new Event('change', {bubbles:true}));
      close();
      input.focus();
      close();
    }
    function render() {
      menu.replaceChildren();
      active = -1;
      input.removeAttribute('aria-activedescendant');
      rows = choices.filter(label => matches(label, input.value)).map((label, index) => {
        const row = document.createElement('div');
        row.id = menu.id + '-' + index;
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', 'false');
        row.textContent = label;
        row.addEventListener('pointerdown', event => {event.preventDefault(); event.stopPropagation(); choose(index);});
        menu.append(row);
        return row;
      });
      if (!rows.length) {
        const empty = document.createElement('div');
        empty.setAttribute('role', 'status');
        empty.textContent = 'No matching students. Check the name or use the new student option.';
        menu.append(empty);
      }
      position();
      menu.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }
    input.addEventListener('focus', render);
    input.addEventListener('input', render);
    input.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key === 'Tab') { close(); return; }
      if (event.key === 'Enter' && !menu.hidden && active >= 0) {
        event.preventDefault(); event.stopImmediatePropagation(); choose(active); return;
      }
      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
      event.preventDefault();
      if (menu.hidden) render();
      if (!rows.length) return;
      active = (active + (event.key === 'ArrowDown' ? 1 : (active < 0 ? 0 : -1)) + rows.length) % rows.length;
      rows.forEach((row, index) => row.setAttribute('aria-selected', String(index === active)));
      input.setAttribute('aria-activedescendant', rows[active].id);
      rows[active].scrollIntoView({block:'nearest'});
    }, true);
    input.addEventListener('blur', close);
    document.addEventListener('pointerdown', event => {if (event.target !== input && !menu.contains(event.target)) close();});
    window.addEventListener('resize', close);
    window.addEventListener('scroll', event => {if (!menu.contains(event.target)) close();}, true);
    input.form?.addEventListener('submit', close);
  }
  function init() {
    document.querySelectorAll('input[list]').forEach(input => {
      if (input.classList.contains('student-picker-compact') || /student/i.test(input.getAttribute('list'))) bind(input);
    });
  }
  init();
  new MutationObserver(init).observe(document.body, {childList:true, subtree:true});
})();
