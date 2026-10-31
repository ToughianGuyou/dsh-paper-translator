import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { runWorker } from '../lib/bridge.js'
const defaults = { pythonExecutable: 'python3', timeoutMs: 3000, maxResponseBytes: 4096 }
const envelope = { ok: true, code: 'OK', message: 'test', pages: [], retryable: false, nextAction: 'done', data: {} }
async function executable(t, body) {
  const directory = await mkdtemp(join(tmpdir(), 'pdf-bridge-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  const path = join(directory, 'worker launcher')
  await writeFile(path, `#!/usr/bin/env python3\n${body}\n`, { mode: 0o700 })
  return path
}
test('missing executable is a structured dependency error', async () => {
  const r = await runWorker('pdf_job_status', {}, { ...defaults, pythonExecutable: '/does/not/exist/python' })
  assert.equal(r.code, 'DEPENDENCY_MISSING')
  assert.equal(r.data.configuredPythonExecutable, '/does/not/exist/python')
  assert.match(r.message, /id: dsh-paper-translator/)
  assert.match(r.message, /WindowsApps/)
})
test('already cancelled launches no worker', async () => {
  const controller = new AbortController(); controller.abort()
  const r = await runWorker('pdf_prepare', {}, defaults, controller.signal)
  assert.equal(r.code, 'CANCELLED')
})
test('JSON stdin roundtrip treats shell characters as inert data', async t => {
  const exe = await executable(t, `import json,sys\nr=json.load(sys.stdin)\nx=${JSON.stringify(envelope).replaceAll('true','True').replaceAll('false','False')}\nx['data']=r['args']\nprint(json.dumps(x))`)
  const args = { path: 'paper; $(touch exploit).pdf' }
  const r = await runWorker('pdf_prepare', args, { ...defaults, pythonExecutable: exe })
  assert.deepEqual(r.data, args)
})
test('invalid worker output is not accepted', async t => {
  const exe = await executable(t, 'print("not JSON")')
  const r = await runWorker('pdf_export', {}, { ...defaults, pythonExecutable: exe })
  assert.equal(r.code, 'WORKER_PROTOCOL_ERROR')
})
test('worker output is bounded', async t => {
  const exe = await executable(t, 'print("x" * 100000)')
  const r = await runWorker('pdf_read_blocks', {}, { ...defaults, pythonExecutable: exe })
  assert.equal(r.code, 'RESPONSE_TOO_LARGE')
})
test('timeout kills worker before returning', async t => {
  const exe = await executable(t, 'import time\ntime.sleep(60)')
  const r = await runWorker('pdf_prepare', {}, { ...defaults, pythonExecutable: exe, timeoutMs: 50 })
  assert.equal(r.code, 'WORKER_TIMEOUT')
})
test('abort during worker execution cancels the process', async t => {
  const exe = await executable(t, 'import time\ntime.sleep(60)')
  const controller = new AbortController()
  const work = runWorker('pdf_prepare', {}, { ...defaults, pythonExecutable: exe }, controller.signal)
  setTimeout(() => controller.abort(), 50)
  assert.equal((await work).code, 'CANCELLED')
})
test('oversized requests rejected before spawn', async () => {
  const r = await runWorker('pdf_submit_translations', { text: 'x'.repeat(10000) }, defaults)
  assert.equal(r.code, 'REQUEST_TOO_LARGE')
})

test('nonworking interpreter identifies the configured path and configuration migration', async t => {
  const exe = await executable(t, 'import sys; sys.exit(9009)')
  const r = await runWorker('html_prepare', {}, { ...defaults, pythonExecutable: exe })
  assert.equal(r.code, 'WORKER_FAILED')
  assert.equal(r.data.configuredPythonExecutable, exe)
  assert.equal(r.data.expectedPluginId, 'dsh-paper-translator')
  assert.match(r.message, /cordis.patch.yml/)
})

test('worker launcher receives a fixed UTF-8 pipe encoding', async t => {
  const exe = await executable(t, `import json,os\nx=${JSON.stringify(envelope).replaceAll('true','True').replaceAll('false','False')}\nx['data']={'encoding':os.environ.get('PYTHONIOENCODING')}\nprint(json.dumps(x))`)
  const r = await runWorker('pdf_job_status', {}, { ...defaults, pythonExecutable: exe })
  assert.equal(r.ok, true)
  assert.equal(r.data.encoding, 'utf-8')
})

test('invalid UTF-8 inside otherwise valid JSON is rejected instead of replaced', async t => {
  const exe = await executable(t, `import json,sys\nx=${JSON.stringify(envelope).replaceAll('true','True').replaceAll('false','False')}\nx['message']='中文'\nsys.stdout.buffer.write(json.dumps(x,ensure_ascii=False).encode('cp936'))`)
  const r = await runWorker('pdf_read_blocks', {}, { ...defaults, pythonExecutable: exe })
  assert.equal(r.ok, false)
  assert.equal(r.code, 'WORKER_ENCODING_ERROR')
})

test('UTF-8 characters split across stdout chunks roundtrip without replacement', async t => {
  const text = '中文路径/日本語/한국어/Русский/😀'
  const exe = await executable(t, `import json,sys\nx=${JSON.stringify(envelope).replaceAll('true','True').replaceAll('false','False')}\nx['data']={'text':${JSON.stringify(text)}}\nfor b in json.dumps(x,ensure_ascii=False).encode('utf-8'):\n sys.stdout.buffer.write(bytes([b])); sys.stdout.buffer.flush()`)
  const r = await runWorker('pdf_read_blocks', {}, { ...defaults, pythonExecutable: exe })
  assert.equal(r.ok, true)
  assert.equal(r.data.text, text)
})
