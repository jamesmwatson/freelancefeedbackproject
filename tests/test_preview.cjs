// Exercise the preview's actual inline data adapter without a browser dependency.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../examples/preview.html'),'utf8');
const js=html.split('<script>')[1].split('</script>')[0];
new vm.Script(js);
assert.equal(/\bfetch\s*\(/.test(js),false);
const ctx={document:{getElementById:()=>({})}};
vm.createContext(ctx);
vm.runInContext(js.slice(0,js.indexOf('function save(')),ctx);
(async()=>{
 const d=await ctx.api('/api/data');
 assert.equal(d.rows.length,4);
 const f={q:'',extension:'',sender:'',from:'',to:'',state:'',template:false,outgoing:false};
 assert.equal(d.rows.filter(r=>ctx.match(r,f)).length,3);
 assert.equal(d.rows.filter(r=>ctx.match(r,{...f,q:'blank'})).length,1);
 assert.equal((await ctx.api('/api/detail?id=1')).contexts.length,2);
 await ctx.api('/api/decision',{body:JSON.stringify({ids:['1'],triage_status:'possible_feedback'})});
 assert.equal((await ctx.api('/api/data')).rows[0].triage_status,'possible_feedback');
 await ctx.api('/api/decision',{body:JSON.stringify({ids:['2'],template:true})});
 assert.equal((await ctx.api('/api/data')).rows[1].template,true);
 assert.equal((await ctx.api('/api/data')).rows[1].triage_status,'unreviewed');
 console.log('Preview JavaScript syntax, embedded fixture, filtering and decision adapter passed.');
})().catch(e=>{console.error(e);process.exit(1)});
