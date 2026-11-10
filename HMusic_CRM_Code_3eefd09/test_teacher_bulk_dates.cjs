const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/app.py','utf8');
const start=source.indexOf('        function teacherMultiSelectedIds()');
const end=source.indexOf('        function teacherWeekdayFromDate',start);
const code=source.slice(start,end).replaceAll('{{','{').replaceAll('}}','}');
function setup(){
 const alerts=[],cards=[['1','2026-11-10'],['2','2026-11-10'],['3','2026-11-11']].map(([id,date])=>({dataset:{id,date},cb:{value:id,checked:false},querySelector(){return this.cb},classList:{toggle(){}}}));
 const els={teacherSelectFrom:{value:'2026-11-10'},teacherSelectThrough:{value:'2026-11-10'},teacherMultiCount:{},teacherMultiBar:{classList:{toggle(){}}},teacherCalendarGrid:{classList:{toggle(){}}},teacherMultiToggle:{classList:{toggle(){}},setAttribute(){}},teacherMultiAction:{value:'set_status'},teacherMultiStatus:{value:'present',selectedOptions:[{textContent:'Present'}]}};
 const sent=[],confirms=[];let resolve;
 const ctx={document:{getElementById:id=>els[id],querySelectorAll:selector=>selector==='.teacher-mobile-calendar'?[]:selector.includes(':checked')?cards.filter(c=>c.cb.checked).map(c=>c.cb):selector==='.teacher-select-input'?cards.map(c=>c.cb):cards},alert:m=>alerts.push(m),confirm:m=>(confirms.push(m),true),window:{HMUSIC_CSRF_TOKEN:'test'},fetch:(url,opts)=>{sent.push(JSON.parse(opts.body));return new Promise(r=>resolve=r)},location:{reload(){}}};
 vm.createContext(ctx);vm.runInContext('let teacherMultiOn=false;'+code,ctx);return {ctx,cards,els,alerts,sent,confirms};
}
let t=setup();t.ctx.teacherMultiSelectDates();assert.deepEqual(t.cards.map(c=>c.cb.checked),[true,true,false]);assert.equal(t.els.teacherMultiCount.textContent,2);
t.ctx.teacherMultiApply();t.ctx.teacherMultiApply();assert.equal(t.sent.length,1);assert.equal(t.sent[0].status,'present');assert.equal(t.confirms[0],'Update 2 selected lesson(s) to Present?');
t=setup();t.ctx.teacherMultiSelectDates('2026-11-10','2026-11-11');assert.equal(t.els.teacherMultiCount.textContent,3);t.ctx.teacherMultiSelectDates('2026-11-11','2026-11-11');assert.deepEqual(t.cards.map(c=>c.cb.checked),[false,false,true]);
t.ctx.teacherMultiSelectDates('2026-11-12','2026-11-10');assert.equal(t.alerts.length,1);assert.equal(t.els.teacherMultiCount.textContent,1);
t=setup();t.ctx.teacherMultiSelectDates();t.els.teacherMultiStatus.value='teacher_cancelled';t.ctx.teacherMultiApply();assert.equal(t.sent[0].notify_parent_on_teacher_cancel,true);
console.log('Passed: day/range selection, replacement, invalid range, confirmation, repeat-submit guard, parent notification contract.');
