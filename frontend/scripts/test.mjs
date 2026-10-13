import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import path from 'node:path';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = path.resolve(import.meta.dirname, '..');

function environment() {
  const data = new Map();
  const storage = { getItem:k=>data.get(k)??null, setItem:(k,v)=>data.set(k,v), removeItem:k=>data.delete(k) };
  const window = new EventTarget();
  window.localStorage = storage; window.sessionStorage = storage;
  const scope = vm.createContext({window, console, Event, CustomEvent, AbortController, AbortSignal, DOMException,
    URL, URLSearchParams, Headers, Response, TextDecoder, crypto:globalThis.crypto, fetch:(...args)=>scope.fetchImpl(...args)});
  const modules = new Map();
  function load(name, parent = root) {
    if (name === 'react') return {useEffect: fn => fn(), useSyncExternalStore: (subscribe, snapshot) => {subscribe(()=>{});return snapshot();}};
    const file = (name.startsWith('.') ? path.resolve(parent, name) : path.join(root, name.replace(/^@\//,''))) + '.ts';
    if (modules.has(file)) return modules.get(file).exports;
    const record = {exports:{}}; modules.set(file,record);
    const code = ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
    vm.runInContext(`(function(exports,require,module){${code}\n})`,scope,{filename:file})(record.exports,name=>load(name,path.dirname(file)),record);
    return record.exports;
  }
  return {load,scope,window,data,storage};
}

test('account caches isolate users and retain unclaimed legacy reports',()=>{
  const env=environment(); const api=env.load('@/lib/browser-storage');
  env.data.set('cryptorisk.analysisRecords','legacy');
  api.setAccountScope('alice'); api.localStore.setItem('cryptorisk.analysisRecords','alice report');
  const aliceSignal=api.getAccountSignal(); api.setAccountScope('bob');
  assert.equal(aliceSignal.aborted,true); assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),null);
  api.localStore.setItem('cryptorisk.analysisRecords','bob report'); api.setAccountScope('alice');
  assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),'alice report');
  assert.equal(env.data.get('cryptorisk.analysisRecords'),'legacy');
  api.clearCurrentAccountStorage(); assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),null);
  api.setAccountScope('bob'); assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),'bob report');
});

test('storage quota and unavailable storage fall back with a warning',()=>{
  const env=environment(); const api=env.load('@/lib/browser-storage'); let warnings=0;
  env.window.addEventListener(api.storageWarningEvent,()=>warnings++);
  Object.defineProperty(env.window,'localStorage',{get(){throw new Error('SecurityError')}});
  api.localStore.setItem('draft','中文 🌏'); assert.equal(api.localStore.getItem('draft'),'中文 🌏');
  api.localStore.removeItem('draft'); assert.equal(api.localStore.getItem('draft'),null); assert.equal(warnings,1);
});

test('cache invalidation does not allow an old response to repopulate cache',async()=>{
  const env=environment();const api=env.load('@/lib/api');const resolvers=[];let calls=0;
  env.scope.fetchImpl=()=>{calls++;return new Promise(resolve=>resolvers.push(resolve))};
  const old=api.fetchRiskOverview(); api.clearApiCache();const fresh=api.fetchRiskOverview();
  resolvers[1](Response.json({version:2}));await fresh;
  resolvers[0](Response.json({version:1}));await old;
  assert.equal((await api.fetchRiskOverview()).version,2); assert.equal(calls,2);
});

test('requestJson keeps Headers instances, CSRF and Pydantic validation messages',async()=>{
  const env=environment();const api=env.load('@/lib/api');let sent;
  env.scope.fetchImpl=async(_url,init)=>{sent=init;return Response.json({detail:[{msg:'请输入有限正数'}]},{status:422})};
  await assert.rejects(api.requestJson('/api/user-assets',{method:'POST',headers:new Headers({'X-Test':'ok'})}),/请输入有限正数/);
  assert.equal(sent.headers.get('X-Test'),'ok'); assert.equal(sent.headers.get('X-CryptoRisk-CSRF'),'1');
});

test('SSE decodes split UTF-8, CRLF, multiline JSON and a final event without blank line',async()=>{
  const {readEventStream}=environment().load('@/lib/event-stream');const text=': ping\r\nevent: chunk\r\ndata: {"content":\r\ndata: "中文 🌏"}\r\n\r\nevent: result\ndata: {"ok":true}';
  const bytes=new TextEncoder().encode(text);let offset=0;const events=[];
  const body=new ReadableStream({pull(c){if(offset>=bytes.length)c.close();else c.enqueue(bytes.slice(offset,++offset));}});
  await readEventStream(new Response(body),(name,data)=>events.push({name,data}));
  assert.equal(events.length,2);assert.equal(events[0].data.content,'中文 🌏');assert.equal(events[1].data.ok,true);
});

test('malformed SSE cancels and releases its reader',async()=>{
  const {readEventStream}=environment().load('@/lib/event-stream');let cancelled=false;
  const body=new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: broken\n\n'));},cancel(){cancelled=true}});
  await assert.rejects(readEventStream(new Response(body),()=>{}),/数据格式异常/);
  assert.equal(cancelled,true); assert.equal(body.locked,false);
});

test('assistant treats empty or interrupted streams as failure',async()=>{
  const env=environment();const api=env.load('@/lib/api');env.scope.fetchImpl=async()=>new Response('event: done\ndata: {}\n\n');
  await assert.rejects(api.streamRiskAssistant('hi',{},()=>{}),/未收到回答/);
  await assert.rejects(api.streamChatMessage('hi',()=>{}),/未收到完整报告/);
});

test('SSE bounds even a complete oversized event in a single network chunk',async()=>{
  const {readEventStream}=environment().load('@/lib/event-stream');let dispatched=false;
  const body='data: '+JSON.stringify({content:'x'.repeat(4_000_001)})+'\n\n';
  await assert.rejects(readEventStream(new Response(body),()=>{dispatched=true}),/响应过大/);
  assert.equal(dispatched,false);
});


test('navigation rejects protocol-relative, backslash and executable URLs', () => {
  const {load} = environment(); const {safeInternalPath, safeHttpUrl} = load('@/lib/safe-url');
  for (const value of ['//evil.test', '/\\evil.test', '/\tevil.test', 'https://evil.test']) assert.equal(safeInternalPath(value), '');
  assert.equal(safeInternalPath('/news?range=7d'), '/news?range=7d');
  for (const value of ['javascript:alert(1)', 'data:text/html,hello', 'file:///etc/passwd', '//evil.test']) assert.equal(safeHttpUrl(value), '');
  assert.equal(safeHttpUrl('https://example.com/news'), 'https://example.com/news');
});


test('market candles merge revisions, sort and bound history', () => {
  const {load}=environment();const {mergeCandles}=load('@/lib/market');
  const candle=(time,close=10)=>({time,open:10,high:12,low:8,close,volume:1});
  const rows=mergeCandles([candle(2),candle(1)],[candle(2,11),candle(3),candle(4)],3);
  assert.deepEqual(Array.from(rows,row=>row.time),[2,3,4]);assert.equal(rows[0].close,11);
  assert.equal(mergeCandles([], [{...candle(1),close:NaN}]).length,0);
});

test('market indicators have correct warmup and flat-market RSI', () => {
  const {load}=environment();const {sma,ema,rsi}=load('@/lib/market');
  const candles=Array.from({length:30},(_,i)=>({time:i+1,open:10,high:11,low:9,close:10,volume:1}));
  assert.equal(sma(candles,10).length,21);assert.equal(ema(candles,20).length,11);
  assert.ok(rsi(candles).every(point=>point.value===50));
  const increasing=candles.map((c,i)=>({...c,close:i+1}));
  assert.equal(sma(increasing,10)[0].value,5.5);assert.equal(rsi(increasing)[0].value,100);
});


test('market size formatting does not turn small nonzero orders into zero', () => {
  const {load}=environment();const {compact}=load('@/lib/market');
  assert.equal(compact(0.00014),'0.00014');assert.notEqual(compact(1e-10),'0');
  assert.equal(compact(undefined),'—');
});


test('legacy portfolio links only resolve to supported markets or follow management',()=>{
  const {legacyPortfolioTarget,normalizeMarketSymbol}=environment().load('@/lib/market-symbols');
  assert.equal(legacyPortfolioTarget('btc'),'/market?symbol=BTCUSDT');
  for(const value of ['TON','../../settings','https://bad.example','',null]) assert.equal(legacyPortfolioTarget(value),'/my?tab=assets');
  assert.equal(normalizeMarketSymbol('SOLUSDT'),'SOLUSDT');
});

const flush=()=>new Promise(resolve=>setImmediate(resolve));
const followRow=symbol=>({symbol,base_asset:symbol.replace(/USDT$/,''),name:symbol,alert_threshold:70,created_at:'old',updated_at:'old'});
test('guest follows stay local and are never silently imported at login',async()=>{
  const env=environment(),storage=env.load('@/lib/browser-storage'),follows=env.load('@/lib/follows');const requests=[];
  env.scope.fetchImpl=async(url,init)=>{requests.push({url,method:init.method||'GET'});return Response.json({items:[],revision:'alice-empty'})};
  follows.useFollows();assert.equal(await follows.changeFollow('TONUSDT','add'),true);
  assert.ok(follows.readGuestFollows().includes('TONUSDT'));assert.equal(requests.length,0);
  storage.setAccountScope('alice');await flush();
  assert.equal(follows.useFollows().items.length,0);assert.ok(requests.every(r=>r.method==='GET'));
  storage.setAccountScope(null);assert.ok(follows.useFollows().items.some(item=>item.symbol==='TONUSDT'));
});

test('follow saves serialize, deduplicate clicks and retain state on failure',async()=>{
  const env=environment(),storage=env.load('@/lib/browser-storage'),follows=env.load('@/lib/follows');
  storage.setAccountScope('alice');let resolveMutation;let writes=0;
  env.scope.fetchImpl=async(_url,init)=>{if(!init.method||init.method==='GET')return Response.json({items:[],revision:'empty'});writes++;return new Promise(resolve=>{resolveMutation=resolve})};
  follows.useFollows();await flush();
  const pending=follows.changeFollow('BTCUSDT','add');await flush();assert.equal(await follows.changeFollow('BTCUSDT','add'),false);assert.equal(writes,1);
  resolveMutation(Response.json({items:[followRow('BTCUSDT')],revision:'saved'}));assert.equal(await pending,true);
  env.scope.fetchImpl=async()=>Response.json({detail:'保存失败'},{status:500});
  assert.equal(await follows.changeFollow('BTCUSDT','remove'),false);assert.equal(follows.useFollows().items.length,1);assert.match(follows.useFollows().error,/保存失败/);
});

test('late follow response cannot cross account boundaries',async()=>{
  const env=environment(),storage=env.load('@/lib/browser-storage'),follows=env.load('@/lib/follows');let resolveMutation;
  storage.setAccountScope('alice');
  env.scope.fetchImpl=async(_url,init)=>init.method==='POST'?new Promise(resolve=>{resolveMutation=resolve}):Response.json({items:[],revision:'empty'});
  follows.useFollows();await flush();const save=follows.changeFollow('BTCUSDT','add');await flush();
  storage.setAccountScope('bob');await flush();resolveMutation(Response.json({items:[followRow('BTCUSDT')],revision:'alice'}));assert.equal(await save,false);
  assert.equal(follows.useFollows().scope,'bob');assert.equal(follows.useFollows().items.length,0);
});


test('malformed follow responses cannot replace a usable list',()=>{
  const {parseFollowSnapshot}=environment().load('@/lib/follows');
  for(const value of [null,{}, {items:null,revision:'1'}, {items:[{}],revision:'1'}, {items:[{...followRow('BTCUSDT'),alert_threshold:NaN}],revision:'1'}])assert.throws(()=>parseFollowSnapshot(value),/格式异常/);
  assert.equal(parseFollowSnapshot({items:[followRow('BTCUSDT'),followRow('BTCUSDT')],revision:'1'}).items.length,1);
});

test('AttackPilot incomplete analyses never produce risk scores',()=>{
  const {analyzeAgentConsistency}=environment().load('@/components/attackpilot/utils/agentConsistency');
  for (const status of ['failed','running','pending','cancelled','completed']) {
    const result=analyzeAgentConsistency({status,final_report:null},[{type:'LOG',agent:'Workflow',message:'failed'}],null);
    assert.equal(result.status,'unavailable');assert.equal(result.score,null);assert.equal(result.checks.length,0);
  }
  const completed=analyzeAgentConsistency({status:'completed',final_report:'Root cause: withdraw() violates invariant.'},[],null);
  assert.equal(typeof completed.score,'number');assert.equal(completed.checks.length,5);
});
