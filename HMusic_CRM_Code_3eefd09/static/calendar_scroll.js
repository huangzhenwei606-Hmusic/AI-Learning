(function () {
  'use strict';
  const key = 'hmusic:owner-calendar-status-scroll';
  function pageKey() {
    const url = new URL(location.href);
    url.searchParams.delete('_workspace');
    url.searchParams.sort();
    return url.pathname + url.search;
  }
  window.rememberCalendarStatusScroll = function (select) {
    const grid = document.querySelector('.cal-grid-wrap');
    try {
      sessionStorage.setItem(key, JSON.stringify({
        page: pageKey(), time: Date.now(), x: window.scrollX, y: window.scrollY,
        gridX: grid ? grid.scrollLeft : 0,
        scheduleId: select.dataset.scheduleId
      }));
    } catch (_) { /* Attendance can still save when storage is unavailable. */ }
  };
  function restore() {
    let saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (!saved || saved.page !== pageKey()) return;
      sessionStorage.removeItem(key);
    } catch (_) { return; }
    if (Date.now() - saved.time > 120000) return;
    function apply() {
      const grid = document.querySelector('.cal-grid-wrap');
      if (grid) grid.scrollLeft = Number(saved.gridX) || 0;
      window.scrollTo({left: Number(saved.x) || 0, top: Number(saved.y) || 0, behavior: 'instant'});
      const select = Array.from(document.querySelectorAll('.calendar-status-select'))
        .find(item => item.dataset.scheduleId === saved.scheduleId);
      if (select) select.focus({preventScroll: true});
    }
    requestAnimationFrame(() => requestAnimationFrame(apply));
  }
  if (document.readyState === 'complete') restore();
  else window.addEventListener('load', restore, {once: true});
})();
