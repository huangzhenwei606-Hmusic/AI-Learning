'use strict';
document.querySelectorAll('[data-audience-widget]').forEach(widget=>{
 const data=JSON.parse(widget.querySelector('[data-audience-data]').textContent), families=data.families, form=widget.closest('form');
 const byId=new Map(families.map(f=>[f.id,f]));
 const chosen=new Set(data.rule.selected.map(Number)), excluded=new Set(data.rule.exclude.map(Number));
 const one=s=>widget.querySelector(s), all=s=>Array.from(widget.querySelectorAll(s));
 const values=n=>all(`input[name="${n}"]:checked`).map(x=>x.value);
 let selected=[];
 const matches=(f,q)=>(f.name+' '+f.students.join(' ')).toLowerCase().includes(q.toLowerCase());
 const detail=f=>`${f.students.join(', ')||'No linked student'} · ${f.category==='current'?'Current':f.category==='past'?'Past':'Needs review'} · Last attended: ${f.last||'Not recorded'} · Next lesson: ${f.next||'None'}`;
 function row(f,set,name){
  const label=document.createElement('label');label.className='family-row';label.dataset.search=(f.name+' '+f.students.join(' ')).toLowerCase();label.dataset.id=f.id;
  const check=document.createElement('input');check.type='checkbox';check.name=name;check.value=f.id;check.checked=set.has(f.id);
  check.addEventListener('change',()=>{check.checked?set.add(f.id):set.delete(f.id);update();});
  const span=document.createElement('span'),title=document.createElement('strong'),info=document.createElement('small');title.textContent=f.name;info.textContent=detail(f);span.append(title,info);label.append(check,span);return label;
 }
 families.forEach(f=>{one('[data-family-list]').append(row(f,chosen,'parent_ids'));one('[data-exclude-list]').append(row(f,excluded,'exclude_ids'));});
 function update(){
  const mode=one('input[name="audience"]:checked').value,teachers=values('audience_teachers'),courses=values('audience_courses');
  const scope=f=>mode==='selected'?chosen.has(f.id):mode==='teacher'?f.teachers.some(t=>teachers.includes(t)):mode==='course'?f.courses.some(c=>courses.includes(c)):f.category===mode;
  selected=families.filter(f=>scope(f)&&!excluded.has(f.id));
  const q=one('[data-family-search]').value,eq=one('[data-exclude-search]').value;
  all('[data-family-list] .family-row').forEach(el=>{const f=byId.get(Number(el.dataset.id));el.hidden=!(mode==='selected'||scope(f))||!matches(f,q);el.querySelector('input').hidden=mode!=='selected';});
  all('[data-exclude-list] .family-row').forEach(el=>{el.hidden=!matches(byId.get(Number(el.dataset.id)),eq);});
  one('[data-teacher-panel]').hidden=mode!=='teacher';one('[data-course-panel]').hidden=mode!=='course';
  one('[data-recipient-summary]').textContent=`${selected.length} families selected · ${excluded.size} excluded`;
  const emails=selected.filter(f=>f.email_ok).length, channels=values('channels');
  one('[data-delivery-summary]').textContent=`${selected.length} families selected | ${channels.includes('email')?emails+' eligible emails | '+(selected.length-emails)+' missing / blocked emails':'Email not selected'} | ${channels.includes('message')?'Message':'No App notification'}${channels.includes('email')?' + Email':''}`;
  const list=one('[data-recipient-list]');list.replaceChildren();selected.forEach(f=>{const el=document.createElement('div');el.className='family-meta';el.textContent=f.name+' · '+detail(f)+' · '+f.children.map(c=>c.name+': '+c.reason).join('; ');list.append(el);});
 }
 all('input[name="audience"],input[name="channels"],input[name="audience_teachers"],input[name="audience_courses"]').forEach(el=>el.addEventListener('change',update));
 one('[data-family-search]').addEventListener('input',update);one('[data-exclude-search]').addEventListener('input',update);
 form.addEventListener('submit',e=>{const error=!selected.length?'Select at least one family.':!values('channels').length?'Choose Message, Email, or both.':'';one('[data-audience-error]').textContent=error;if(error)e.preventDefault();});
 update();
});
