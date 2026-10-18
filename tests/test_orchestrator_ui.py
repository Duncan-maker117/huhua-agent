"""Execute the actual entry/progress controller with an offline DOM stub."""
from pathlib import Path
import shutil
import subprocess
import unittest


class OrchestratorUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required for DOM regression")
    def test_mode_gating_auto_send_draft_preservation_and_safe_progress(self):
        result = subprocess.run(["node", "-e", r'''
const assert = require('node:assert/strict');
class Element {
  constructor() { this.children = []; this.handlers = {}; this.dataset = {}; this.style = {}; this.attributes = {}; this.hidden = true; this.classList = {add: () => {}}; }
  append(child) { this.children.push(child); }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
}
global.window = {};
global.document = {createElement: () => new Element(), getElementById: () => null};
require('./web/orchestrator-ui.js');
const ui = window.HuhuaOrchestrator;
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  const container = new Element(), legacy = new Element(), sent = [];
  let busy = false, release;
  ui.init({container, legacy, busy: () => busy,
    send: async (...args) => { sent.push(args); await new Promise(resolve => release = resolve); },
    fetcher: async url => { assert.equal(url, '/api/chat/agent-mode'); return {ok:true, json: async () => ({agent_mode:'loop'})}; }});
  await tick();
  assert.equal(legacy.style.display, 'none'); assert.equal(container.hidden, false);
  assert.deepEqual(container.children.map(b => b.children[0].textContent), ['我有 JD', '我有旧简历', '先聊聊我的经历', '看看你能做什么']);
  const button = container.children[0];
  const sending = button.handlers.click();
  await button.handlers.click();
  assert.equal(sent.length, 1); assert.equal(button.disabled, true);
  assert.deepEqual(sent[0][1], {quickReply:true, keepDraft:true});
  release(); await sending; assert.equal(button.disabled, false);
  busy = true; await button.handlers.click(); assert.equal(sent.length, 1);
  for (const mode of ['off', undefined]) {
    const other = new Element(), old = new Element();
    ui.init({container:other, legacy:old, busy:()=>false, send:()=>{}, fetcher:async()=>({ok:true,json:async()=>({agent_mode:mode})})});
    await tick(); assert.equal(other.children.length, 0); assert.equal(old.style.display, undefined);
  }
  const parent = new Element(), progress = ui.progress(parent);
  progress({tool:'record_facts',status:'running',message:'正在记录'});
  progress({tool:'record_facts',status:'completed',message:'<img src=x onerror=alert(1)>'});
  assert.equal(parent.children.length, 1);
  assert.equal(parent.children[0].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(parent.children[0].innerHTML, undefined);
  assert.equal(parent.children[0].attributes.role, 'status');
  assert.equal(parent.children[0].dataset.status, 'completed');
  progress({tool:'write_draft',status:'running',message:'正在写稿'});
  assert.equal(parent.children.length, 2);
  progress({tool:'unknown',status:'unrecognized'}); assert.equal(parent.children.length, 2);
})().catch(error => { console.error(error); process.exitCode=1; });
'''], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
