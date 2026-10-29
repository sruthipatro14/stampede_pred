// No browser/package dependency: targeted renderer contract tests, not visual QA.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.style={};this.value='';this.classList={toggle(){},remove(){},add(){}}}
 append(...nodes){this.children.push(...nodes)} replaceChildren(...nodes){this.children=nodes}
 setAttribute(){} getContext(){return new Proxy({}, {get:()=>()=>{}})}
 get text(){return (this.textContent||'')+' '+this.children.map(c=>c.text||'').join(' ')}
}
const nodes=new Map(),document={querySelector(s){if(!nodes.has(s))nodes.set(s,new Element());return nodes.get(s)},createElement:t=>new Element(t),addEventListener(){},body:new Element()};
const context=vm.createContext({document,Date,Number,Map,Set,Math,console,setInterval(){},window:{}});
const code=fs.readFileSync('dashboard/index.html','utf8').split('<script>')[1].split('</script>')[0];
vm.runInContext(code.slice(0,code.indexOf('let polling=false')),context);
const evaluate=s=>vm.runInContext(s,context);
assert.equal(evaluate('num(null)'),'Unavailable');assert.equal(evaluate('num(NaN)'),'Unavailable');// This helper formats density bands only. Backend event level 0 remains intact.
assert.equal(evaluate('level(0)'),'Unavailable');
for(const n of [1,2,3,4])assert.equal(evaluate('level('+n+')'),'L'+n);
assert.equal(evaluate("fresh({source_status:'live',timestamp:new Date(Date.now()-6000).toISOString()})"),false);
assert.equal(evaluate("fresh({source_status:'finished',timestamp:new Date().toISOString()})"),false);
const gate=evaluate('createAlertSoundGate()');const event={id:'test',channels:['sound'],time:new Date().toISOString()};assert.equal(gate([event]).length,0);assert.equal(gate([{...event,id:'new'}]).length,1);assert.equal(gate([{...event,id:'new'}]).length,0);
context.tile={badge:new Element(),veil:new Element(),details:new Element(),timing:new Element()};
context.state={source_status:'live',source_type:'SYNTHETIC DEMO',timestamp:new Date().toISOString(),zones:[0,1].map(i=>({name:'Zone '+i,category:i?'stair':'level',level:3,density_level:2,persistent_level:2,people:12.5,density:2,thresholds:i?[1.5,2.5,3.3]:[2,4,6],sample_timestamp:new Date().toISOString(),forecast_30:2,forecast_60:3,forecast_120:4,forecast_levels:{30:2,60:3,120:4},eta_to_L4:null,eta_state:'beyond_horizon',active_overrides:[],trigger:'forecast +60s'})),links:[],stages:{}};
evaluate('render(tile,state,[])');assert.equal(context.tile.details.children[1].children.length,2);assert(context.tile.details.text.includes('No crossing within 120 s'));assert(!context.tile.details.text.includes('Not rising'));
const cards=context.tile.details.children[1].children;
for(const card of cards){
 const forecast=card.children.find(c=>c.className==='forecast-grid');assert.equal(forecast.children.length,3);
 assert(forecast.text.includes('+30 s'));assert(forecast.text.includes('+60 s'));assert(forecast.text.includes('+120 s'));
 const details=card.children.find(c=>c.tag==='details');assert.equal(details.open,false);assert(details.text.includes('Persistent level:'));assert(details.children.some(c=>c.tag==='canvas'));
 assert(!card.children.filter(c=>c.tag!=='details').map(c=>c.text).join(' ').includes('Persistent level:'));
}
const detail=cards[0].children.find(c=>c.tag==='details');detail.open=true;detail.ontoggle();evaluate('render(tile,state,[])');assert.equal(context.tile.details.children[1].children[0].children.find(c=>c.tag==='details').open,true);
context.state.zones[0].eta_state='not_rising';evaluate('render(tile,state,[])');assert(context.tile.details.text.includes('Not rising'));assert(context.tile.details.text.includes('Forecast does not currently reach L4.'));
context.state.zones[0].eta_state='unavailable';evaluate('render(tile,state,[])');assert(!context.tile.details.children[1].children[0].text.includes('Not rising'));
context.state.zones[0].sample_timestamp='bad';evaluate('render(tile,state,[])');assert(context.tile.details.children[1].children[0].text.includes('Unavailable'));
context.state.timestamp=new Date(Date.now()-6000).toISOString();evaluate('render(tile,state,[])');assert(!context.tile.details.text.includes('12.5'));assert(context.tile.details.text.includes('masked together'));
console.log('PASS: compact every-zone summaries, collapsed/persistent details, justified Not rising copy, density-band formatter (L1–L4; event 0 unchanged), stale/source masking, silent initial sound, deduplication, every-zone forecasts, ETA and missing samples');
// History UI tests use synthetic events and mocked fetch only; no notifications.
context.events=[
 {id:'b',time:'2026-10-28T12:01:00Z',camera:'B',zone:'Link',level:0,kind:'bottleneck',trigger:'width_ratio>1.5',drill:false,acknowledgement:{staff:'<staff>',timestamp:'2026-10-28T12:02:00Z'}},
 {id:'a',time:'2026-10-28T12:00:00Z',camera:'A',zone:'Z',level:3,kind:'level',trigger:'forecast +60s',drill:true},
 {id:'c',time:'2026-10-28T12:03:00Z',camera:'A',zone:'Z2',level:2,kind:'level',trigger:'current',drill:false},
 {}];
assert.equal(evaluate('filteredAlerts(events)[0].id'),'c');
for(const [filter,value,expected]of [['camera','B',1],['level','0',1],['kind','level',2],['drill','yes',1],['ack','yes',1],['ack','no',3]]){
 context.filters={[filter]:value};assert.equal(evaluate('filteredAlerts(events,filters).length'),expected);
}
assert.equal(evaluate("triggerText('current')"),'Current-density trigger');assert.equal(evaluate("triggerText('forecast +60s')"),'Forecast threshold crossing: +60 s.');
evaluate('alertRows=events;renderAlerts()');assert.equal(nodes.get('#feed').children.length,4);assert(nodes.get('#feed').text.includes('DRILL'));assert(nodes.get('#feed').text.includes('By <staff>'));assert(nodes.get('#feed').text.includes('Time unavailable'));assert(nodes.get('#feed').text.includes('Event has no ID'));
const acked=nodes.get('#feed').children.find(c=>c.text.includes('By <staff>'));assert(!acked.children[2].children.some(c=>c.tag==='button'));
evaluate("pendingAcks.add('a');renderAlerts()");assert(nodes.get('#feed').children.find(c=>c.text.includes('DRILL')).children[2].children.find(c=>c.tag==='button').disabled);evaluate("pendingAcks.clear()");
context.state.timestamp=new Date().toISOString();context.state.links=[{link:'Zone 0->Zone 1',flagged:true,conditions:['width_ratio>1.5','speed<0.5','counterflow','flow>85%cap','queue_growing_flow_flat']}];
evaluate('renderBottlenecks(tile,state)');assert(context.tile.timing.text.includes('Passage narrows'));assert(context.tile.timing.text.includes('Queue growing without increased outflow'));assert(context.tile.timing.text.includes('not end-to-end latency'));assert(context.tile.timing.children.some(c=>c.tag==='details'));
const technical=context.tile.timing.children.find(c=>c.className==='bottleneck-card').children.find(c=>c.tag==='details');assert(technical.text.includes('width_ratio>1.5'));assert(technical.text.includes('not supplied'));
evaluate("alertLimit=500;renderAlerts()");assert(nodes.get('#load-more').disabled);evaluate('alertLimit=25');
async function testAck(){
 document.querySelector('#staff-name').value='';await evaluate('acknowledge(events[1])');assert(nodes.get('#feed').text.includes('Enter a staff name'));
 document.querySelector('#staff-name').value='Test Staff';let finish,calls=0;
 context.fetch=()=>{calls++;return new Promise(resolve=>finish=resolve)};
 const request=evaluate('acknowledge(events[1])');await evaluate('acknowledge(events[1])');assert.equal(calls,1);
 finish({ok:true,json:async()=>({alert_id:'a',staff:'Test Staff',timestamp:'2026-10-28T12:04:00Z'})});await request;assert(nodes.get('#feed').text.includes('By Test Staff'));
 context.fetch=async()=>({ok:false,status:403});await evaluate('acknowledge(events[2])');assert(nodes.get('#feed').text.includes('Access denied'));
 console.log('PASS: alert filters, newest-first ordering, missing fields, individual acknowledgements, validation, pending deduplication, success/error feedback, safe text, bounded list and bottleneck details');
}
testAck().catch(error=>{console.error(error);process.exitCode=1});
