const assert = require('node:assert/strict');
const {matches} = require('./static/student_picker.js');
assert(matches('Hannah Smith · Parent: Alice', 'hannah'));
assert(matches('Hannah Smith · Parent: Alice', 'smith'));
assert(matches('Hannah Smith · Parent: Alice', 'HANNAH sm'));
assert(matches('王小明 · Parent: 陈女士', '小明'));
assert(matches('Hannah Smith · Parent: Alice', 'alice'));
assert(!matches('Hannah Smith · Parent: Alice', 'hh'));
class El {
 constructor() { this.attrs={}; this.dataset={}; this.listeners={}; this.children=[]; this.style={}; this.value=''; this.classList={contains:()=>true}; }
 setAttribute(k,v){this.attrs[k]=v} getAttribute(k){return this.attrs[k]} removeAttribute(k){delete this.attrs[k]}
 append(e){this.children.push(e)} replaceChildren(){this.children=[]}
 addEventListener(k,fn){(this.listeners[k]??=[]).push(fn)}
 dispatchEvent(e){for(const fn of this.listeners[e.type]||[])fn(e)}
 getBoundingClientRect(){return {left:10,top:100,bottom:140,width:300}}
 contains(e){return this.children.includes(e)} scrollIntoView(){} focus(){this.dispatchEvent({type:'focus'})}
}
const input=new El(); input.setAttribute('list','students'); input.form=new El();
const list={options:[{value:'Hannah Smith · Parent: Alice'},{value:'John Lee · Parent: Bob'}]};
global.document={head:new El(),body:new El(),createElement:()=>new El(),getElementById:()=>list,querySelectorAll:()=>[input],addEventListener:()=>{}};
global.window={innerWidth:1000,innerHeight:800,addEventListener:()=>{}};
global.MutationObserver=class {observe(){}};
delete require.cache[require.resolve('./static/student_picker.js')];require('./static/student_picker.js');
const menu=document.body.children[0];
input.value='hannah'; input.dispatchEvent({type:'input'});
assert.equal(menu.children.length,1); assert.equal(menu.children[0].textContent,list.options[0].value);
assert.equal(input.getAttribute('list'),undefined);
let prevented=false;
input.dispatchEvent({type:'keydown',key:'ArrowDown',preventDefault(){}});
input.dispatchEvent({type:'keydown',key:'Enter',preventDefault(){prevented=true},stopImmediatePropagation(){}});
assert(prevented);assert.equal(input.value,list.options[0].value);assert(menu.hidden);
input.value='Lee';input.dispatchEvent({type:'input'});
assert.equal(menu.children[0].textContent,list.options[1].value);
menu.children[0].dispatchEvent({type:'pointerdown',preventDefault(){},stopPropagation(){}});
assert.equal(input.value,list.options[1].value);assert(menu.hidden);
input.value='unknown';input.dispatchEvent({type:'input'});
assert.equal(menu.children[0].getAttribute('role'),'status');
input.dispatchEvent({type:'keydown',key:'Escape',preventDefault(){}});assert(menu.hidden);
input.value='王';input.dispatchEvent({type:'keydown',key:'Enter',isComposing:true});assert.equal(input.value,'王');
console.log('Passed: full/partial surname, Chinese, parent and case matching; input results; keyboard and pointer selection; empty results; Escape; IME.');
