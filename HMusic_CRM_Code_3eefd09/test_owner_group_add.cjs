const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.py','utf8');
const code=source.slice(source.indexOf('    let ownerGroupAddBusy='),source.indexOf('    function collectOwnerGroupAttendance()')).replaceAll('{{','{').replaceAll('}}','}');
(async()=>{
 for(const scope of ['once','following']){
  const elements={panelGroupAddResult:{textContent:''},panelGroupAddStudent:{value:'New child'},panelGroupAddScope:{value:scope},panelGroupAddConfirm:{disabled:false},panelLessonNote:{value:''},panelHomework:{value:''}};
  const calls=[];let dirty=false;
  const ctx={activePanelLesson:{id:7,status:'present',group_students:[{student_name:'A',attendance_status:'present'}]},activePanelStatus:'present',ownerPanelSaving:false,document:{getElementById:id=>elements[id]},window:{HMUSIC_CSRF_TOKEN:'test-token'},collectOwnerGroupAttendance:()=>[{student_name:'A',attendance_status:'present'}],panelDetailsChanged:()=>dirty,panelRemindersChanged:()=>false,fetch:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>({ok:true,message:'Added'})};},openLessonPanel:id=>calls.push(['refresh',id]),showPanelToast:()=>{}};
  vm.createContext(ctx);vm.runInContext(code,ctx);await ctx.ownerAddGroupStudent();
  assert.equal(calls[0][0],'/api/calendar-group-roster/7/add');assert.deepEqual(JSON.parse(calls[0][1].body),{student_name:'New child',scope});assert.equal(calls[0][1].headers['X-CSRFToken'],'test-token');assert.equal(elements.panelGroupAddConfirm.disabled,false);
  dirty=true;calls.length=0;await ctx.ownerAddGroupStudent();assert.equal(calls.length,0);assert.match(elements.panelGroupAddResult.textContent,/Save or discard/);
 }
 console.log('Group add UI scope, CSRF and unsaved-change checks passed.');
})().catch(err=>{console.error(err);process.exitCode=1;});
