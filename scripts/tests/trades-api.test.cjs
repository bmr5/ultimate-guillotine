const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHandler } = require('../../api/trades.js');
process.env.TRADES_API_KEY = 'test-only';
process.env.TRADES_DATABASE_URL = 'test-only';
function response() {
  return { headers: {}, setHeader(k,v) { this.headers[k]=v; }, status(s) {this.code=s;return this;}, json(b) {this.body=b;return this;} };
}
test('denies missing and incorrect keys before opening a database connection',async()=>{
 const handler=createHandler(()=>{throw Error('must not connect');});
 for(const headers of [{},{'x-api-key':'wrong'}]) {
  const res=response();await handler({method:'GET',url:'/api/trades',headers},res);assert.equal(res.code,401);
 }
});
test('rejects writes and invalid season filters',async()=>{
 const handler=createHandler(()=>{throw Error('must not connect');});
 for(const [method,url,code] of [['POST','/api/trades',405],['GET','/api/trades?season=2026%20OR%201=1',400]]){
  const res=response();await handler({method,url,headers:{'x-api-key':'test-only'}},res);assert.equal(res.code,code);
 }
});
test('returns both sources with a parameterized season and read-only transaction',async()=>{
 const queries=[];let released=false;
 const handler=createHandler(()=>({connect:async()=>({query:async(text,params)=>{queries.push({text,params});return {rows: text.includes('FROM public.trades')?[{trade_code:'T-2026-001'}]:[]};},release(){released=true;}})}));
 const res=response();await handler({method:'GET',url:'/api/trades?season=2026',headers:{authorization:'Bearer test-only'}},res);
 assert.equal(res.code,200);assert.equal(res.body.counts.registered,1);assert.equal(res.headers['Cache-Control'],'private, no-store');
 assert.match(queries[0].text,/READ ONLY/);assert.deepEqual(queries[1].params,[2026]);assert.equal(queries.at(-1).text,'COMMIT');assert.ok(released);
});
test('database failures return no secrets and release the connection',async()=>{
 let released=false;
 const handler=createHandler(()=>({connect:async()=>({query:async(text)=>{if(text!=='ROLLBACK')throw Error('secret connection string');},release(){released=true;}})}));
 const res=response();await handler({method:'GET',url:'/api/trades',headers:{'x-api-key':'test-only'}},res);
 assert.equal(res.code,503);assert.ok(!JSON.stringify(res.body).includes('secret'));assert.ok(released);
});
