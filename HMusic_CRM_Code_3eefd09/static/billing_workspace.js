(() => {
  const dialog=document.getElementById('billing-task');
  if(!dialog)return;
  const frame=document.getElementById('billing-task-frame');
  const loading=document.getElementById('billing-loading');
  const parentSearch=document.getElementById('billing-family-search');
  const payer=document.getElementById('billing-family');
  if(parentSearch && payer){
    const parents=Array.from(payer.options).slice(1).map(option=>({value:option.value,text:option.text}));
    parentSearch.addEventListener('input',()=>{
      const query=parentSearch.value.trim().toLocaleLowerCase();
      const digits=query.replace(/\D/g,'');
      const found=parents.filter(option=>option.text.toLocaleLowerCase().includes(query) ||
        (digits.length>=3 && /^[+\d\s().-]+$/.test(query) && option.text.split(' · ').slice(2).join('').replace(/\D/g,'').includes(digits)));
      const selected=payer.value;
      payer.replaceChildren(new Option(found.length?'Choose a family…':'No matching parents',''));
      found.forEach(option=>payer.add(new Option(option.text,option.value)));
      payer.value=found.some(option=>option.value===selected)?selected:'';
      document.getElementById('billing-family-count').textContent=query?`${found.length} matching parent(s)`:'';
    });
  }
  function openTask(path,title){
    const url=new URL(path,location.href);
    if(url.origin!==location.origin)return;
    url.searchParams.set('_workspace','1');
    document.getElementById('billing-task-title').textContent=title||'Billing';
    loading.hidden=false; frame.src=url.href; dialog.showModal();
  }
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href]');
    if(!link||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin)return;
    if(/^\/(family_billing\/|family_payment\/|owner\/(invoice\/|quick-pay)|billing_settings$|owner_settings$|notification_center$|edit_invoice\/|pay_invoice\/|parent_invoice\/|students$)/.test(url.pathname)){
      event.preventDefault();openTask(url.href,link.dataset.billingTitle||link.textContent.trim());
    }
  });
  document.getElementById('combine-family-form').addEventListener('submit',event=>{
    event.preventDefault();const id=document.getElementById('billing-family').value;
    if(/^\d+$/.test(id))openTask('/family_billing/'+id,'Combine family invoices');
  });
  frame.addEventListener('load',()=>{loading.hidden=true;});
  document.getElementById('close-billing-task').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>location.reload());
  document.getElementById('refresh-billing').addEventListener('click',()=>location.reload());
})();
