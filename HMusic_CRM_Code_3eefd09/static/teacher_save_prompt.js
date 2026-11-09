(() => {
  'use strict';
  if (window.HMusicTeacherWorkReminderPrompt) return;
  let chain = Promise.resolve();
  window.HMusicTeacherWorkReminderPrompt = urls => {
    if (!Array.isArray(urls) || !urls.length) return Promise.resolve();
    chain = chain.then(async () => {
      for (const url of urls) {
        if (typeof url !== 'string' || !url.startsWith('/manager/teacher-work-reminders/saved/')) continue;
        await new Promise(resolve => {
          const dialog = document.createElement('dialog');
          dialog.setAttribute('aria-label','Lesson saved · notify teacher');
          dialog.style.cssText='width:min(1100px,96vw);max-width:96vw;height:min(850px,94vh);border:1px solid #ccd5e1;border-radius:14px;padding:0;box-shadow:0 20px 80px #0005';
          const bar=document.createElement('div');bar.style.cssText='display:flex;justify-content:space-between;align-items:center;padding:12px 18px;background:#eef4ff';
          const title=document.createElement('strong');title.textContent='Lesson saved · notify teacher';
          const close=document.createElement('button');close.type='button';close.textContent='Close';close.style.cssText='padding:8px 14px;cursor:pointer';
          const frame=document.createElement('iframe');frame.title='Confirm teacher SMS or email';frame.src=url;frame.style.cssText='display:block;border:0;width:100%;height:calc(100% - 60px)';
          bar.append(title,close);dialog.append(bar,frame);document.body.append(dialog);
          const onMessage=e=>{if(e.origin===location.origin && e.source===frame.contentWindow && e.data?.type==='hmusic-teacher-reminder-close')dialog.close();};
          close.onclick=()=>dialog.close();window.addEventListener('message',onMessage);
          dialog.addEventListener('close',()=>{window.removeEventListener('message',onMessage);dialog.remove();resolve();},{once:true});
          dialog.showModal();
        });
      }
    });
    return chain;
  };
})();
