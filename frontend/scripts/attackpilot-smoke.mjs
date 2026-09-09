// Offline browser check: no website server, Next build, model, or chain calls.
// Usage: node scripts/attackpilot-smoke.mjs /tmp/attackpilot-ui-check
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer';

const root = process.cwd();
const temporary = path.resolve(process.argv[2] || '/tmp/attackpilot-ui-check');
const { build } = createRequire(path.join(temporary, 'package.json'))('esbuild');
const fixture = JSON.parse(await readFile(path.join(temporary, 'fixtures.json'), 'utf8'));
const output = path.join(temporary, 'site');
await mkdir(output, { recursive: true });

const navigation = `import React, {useSyncExternalStore} from 'react';
const subscribe = cb => { window.addEventListener('popstate', cb); return () => window.removeEventListener('popstate', cb); };
const push = url => { history.pushState({}, '', url); window.dispatchEvent(new PopStateEvent('popstate')); };
const router = {push, replace:push, back:()=>history.back()};
export function usePathname(){return useSyncExternalStore(subscribe,()=>location.pathname)}
export function useRouter(){return router}
export function useParams(){return {taskId:usePathname().split('/')[3]}}
export default function Link({href,children,...props}) {return <a href={href} {...props} onClick={e=>{e.preventDefault();push(href)}}>{children}</a>}`;
await build({
  stdin: { contents: `import React,{useState} from 'react'; import {createRoot} from 'react-dom/client'; import Workbench from './components/attackpilot/workbench';
    function App(){const [user,setUser]=useState(null); return <><button id="fixture-identity" onClick={()=>setUser(user?null:'alice')}>{user?'退出测试账号':'访客'}</button><Workbench userId={user} onLogin={()=>setUser('alice')} /></>};
    createRoot(document.getElementById('root')).render(<App/>);`, resolveDir: root, loader: 'tsx' },
  outfile: path.join(output, 'check.js'), bundle: true, platform: 'browser', format: 'esm', jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{ name: 'next-test-router', setup(builder) {
    builder.onResolve({filter:/^next\/(link|navigation|dynamic)$/}, args=>({path:args.path, namespace:'test-next'}));
    builder.onLoad({filter:/.*/,namespace:'test-next'}, args=>({contents:args.path==='next/dynamic'
      ? `import React,{lazy,Suspense} from 'react'; export default function dynamic(loader,options={}) {const Component=lazy(loader); return props=><Suspense fallback={options.loading?.()}><Component {...props}/></Suspense>}`
      : navigation, loader:'tsx', resolveDir:root}));
  }}],
});
const js = await readFile(path.join(output, 'check.js'));
const css = await readFile(path.join(output, 'check.css'));
const html = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/check.css"></head><body style="margin:0;background:#f1f5f9;font-family:Arial,sans-serif"><div id="root"></div><script type="module" src="/check.js"></script></body></html>';
const errors = [], missing = [], mutations = [];
const liveId = '00000000-0000-4000-8000-000000000001';
const liveTask = {task_id:liveId,dapp_name:'Offline live task',status:'running',created_at:'2026-01-01T00:00:00Z',is_demo:false};
const browser = await puppeteer.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
try {
  const page = await browser.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    const url = new URL(request.url());
    if (url.origin !== 'https://attackpilot.test') return request.abort();
    if (url.pathname === '/check.js') return request.respond({status:200,contentType:'application/javascript',body:js});
    if (url.pathname === '/check.css') return request.respond({status:200,contentType:'text/css',body:css});
    if (!url.pathname.startsWith('/api/')) return request.respond({status:200,contentType:'text/html',body:html});
    if (request.method() !== 'GET') mutations.push({path:url.pathname,csrf:request.headers()['x-cryptorisk-csrf']});
    if (url.pathname.startsWith('/api/attackpilot/tasks/'+liveId)) {
      const suffix = url.pathname.slice(('/api/attackpilot/tasks/'+liveId).length);
      if (suffix==='/events') return request.respond({status:200,contentType:'text/event-stream',body:'id: 1\ndata: '+JSON.stringify({...liveTask,type:'TASK_FINAL',status:'completed',final_report:'Offline task report',result:{verification:{status:'skipped'}}})+'\n\n'});
      const body = suffix==='' ? liveTask : suffix==='/logs' ? {events:[],has_more:false} : suffix==='/agent-log-files' ? {files:[]} : {detail:'No fixture evidence'};
      return request.respond({status:['','/logs','/agent-log-files'].includes(suffix)?200:404,contentType:'application/json',body:JSON.stringify(body)});
    }
    if (url.pathname.endsWith('/assistant/chat')) return request.respond({status:200,contentType:'application/json',body:JSON.stringify({answer:'离线模拟取证回答：请核对任务证据。',sources:[],model:'offline mock',scope:'task',task_id:fixture.task_id})});
    const response = fixture.responses[url.pathname];
    if (!response) missing.push(url.pathname);
    await request.respond({status:response?.status || 404,contentType:'application/json',body:JSON.stringify(response?.body || {detail:'No offline fixture'})});
  });
  const visit = async route => { await page.goto('https://attackpilot.test'+route,{waitUntil:'networkidle0'}); };
  const contains = text => page.waitForFunction(value=>document.body.innerText.includes(value),{},text);
  const clickText = async text => {
    const found = await page.evaluate(value=>{const item=[...document.querySelectorAll('button,a')].find(node=>node.textContent.trim()===value);item?.click();return !!item;},text);
    assert.ok(found, `Clickable text missing: ${text}`);
  };
  const checkWidth = async label => {
    const sizes = await page.evaluate(()=>({window:innerWidth,document:document.documentElement.scrollWidth}));
    assert.ok(sizes.document<=sizes.window+1, `${label}: horizontal page overflow ${JSON.stringify(sizes)}`);
  };
  await page.setViewport({width:1440,height:1000});
  await visit('/attackpilot'); await contains('从交易线索'); await checkWidth('desktop review');
  await page.type('#ap-hashes','bad-hash'); await contains('请检查 Hash 格式');
  await page.screenshot({path:path.join(output,'review-desktop.png'),fullPage:true});
  await clickText('任务库'); await contains('公共历史示例'); await page.waitForSelector('.ant-table-row');
  await visit('/attackpilot/tasks/'+fixture.task_id); await contains('未在当前环境重新验证'); await contains('结构化报告');
  await checkWidth('desktop detail'); await page.screenshot({path:path.join(output,'detail-desktop.png'),fullPage:true});
  await clickText('访客'); await clickText('取证助手'); await contains('助手会基于当前交易');
  await page.type('.assistant-composer textarea','这份报告有哪些关键证据？'); await clickText('发送'); await contains('离线模拟取证回答');
  await page.screenshot({path:path.join(output,'assistant-desktop.png'),fullPage:true});
  await page.evaluate(id=>{history.pushState({},'', '/attackpilot/tasks/'+id);window.dispatchEvent(new PopStateEvent('popstate'));},liveId);
  await contains('验证已跳过');
  await visit('/attackpilot/knowledge'); await contains('漏洞'); await checkWidth('desktop knowledge');
  for (const [name,route] of [['review','/attackpilot'],['tasks','/attackpilot/tasks'],['detail','/attackpilot/tasks/'+fixture.task_id],['knowledge','/attackpilot/knowledge']]) {
    await page.setViewport({width:390,height:844}); await visit(route);
    await page.waitForSelector('.ap-module-nav'); await checkWidth('mobile '+name);
    await page.screenshot({path:path.join(output,name+'-mobile.png'),fullPage:true});
  }
  await clickText('任务库'); await contains('分析任务库');
  await page.goBack({waitUntil:'networkidle0'}); await contains('漏洞知识库');
  assert.deepEqual(errors, [], 'Unexpected browser errors');
  assert.deepEqual(missing, [], 'Unmocked API calls');
  assert.ok(mutations.every(item=>item.csrf==='1'), 'Mutation request lacks the shared CSRF header');
  await writeFile(path.join(output,'result.json'),JSON.stringify({passed:true,viewports:[1440,390],historicalTask:fixture.task_id,errors,mutations},null,2));
  console.log('AttackPilot offline browser smoke passed; artifacts: '+output);
} finally { await browser.close(); }
