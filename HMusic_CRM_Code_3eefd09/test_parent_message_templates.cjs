const assert=require('node:assert/strict');
const templates=require('./static/parent_message_templates.js');
const l={student:'Group lesson',date:'2026-11-16',time:'16:15',display_time:'04:15 PM–04:45 PM PST',teacher:'Jason',duration:30,location:'Main studio',room:'Room 3'};
const p={name:'Claire',student:'Daniel Peng'};
assert.equal(templates.build('custom',l,p),'');
for(const [kind] of templates.options.slice(1)) {
 const draft=templates.build(kind,l,p);
 for(const value of ['Hi Claire,','Daniel Peng','Monday, November 16, 2026','04:15 PM–04:45 PM PST','Jason','30 minutes','Main studio','Room 3']) assert.ok(draft.includes(value),kind+' missing '+value);
 assert.ok(!/[\u3400-\u9fff]/.test(draft));
}
assert.ok(templates.build('reschedule',l,p).includes('A new time will be confirmed separately'));
assert.ok(!templates.build('reminder',{...l,room:'',location:''},p).includes('Room:'));
assert.equal(templates.build('unknown',l,p),'');
console.log('English editable message templates passed.');
