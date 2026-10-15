"""Run the real browser cancellation helper against a deterministic fetch stub."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ChatCancelBrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for browser module regression')
    def test_cancel_ack_precedes_abort_early_click_and_failure_remains_retryable(self):
        root = Path(__file__).resolve().parents[1]
        script = r'''
const assert = require('node:assert/strict');
const {cancelTurn} = require('./web/chat-cancel.js');
(async () => {
  const order = [];
  let accept;
  const turn = {id:'one', session:'s1', accepted:new Promise(r => accept=r), controller:{abort:() => order.push('abort')}};
  const stop = cancelTurn(turn, async url => {
    order.push('request'); assert.match(url, /s1\/cancel\?turn_id=one$/);
    return {ok:true, json:async () => {order.push('ack'); return {cancelled:true};}};
  });
  await Promise.resolve(); assert.deepEqual(order, []);
  accept(true); assert.equal(await stop, true);
  assert.deepEqual(order, ['request', 'ack', 'abort']);
  assert.equal(turn.cancelled, true);
  await cancelTurn(turn, () => {throw Error('duplicate cancel request');});
  const failed = {id:'two', session:'s1', accepted:Promise.resolve(true), controller:{abort:() => {throw Error('must not abort');}}};
  await assert.rejects(cancelTurn(failed, async () => ({ok:false})), /中断未成功/);
  assert.equal(failed.cancelPromise, null);
  assert.equal(await cancelTurn(failed, async () => ({ok:true,json:async () => ({cancelled:false,status:'committed'})})), false);
  const next = {id:'three',session:'s1',accepted:Promise.resolve(true),controller:{abort:() => order.push('next-abort')}};
  assert.equal(await cancelTurn(next, async url => {
    assert.match(url, /turn_id=three$/); return {ok:true,json:async () => ({cancelled:true})};
  }), true);
})().catch(error => {console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
