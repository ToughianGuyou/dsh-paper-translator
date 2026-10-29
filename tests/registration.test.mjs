/** Offline SDK integration, not a model-backed Harness session. */
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, access } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import * as toolsSdk from '@deepseek-ai/dsh-tools'
const { ToolArgsError, validateJsonSchemaValue } = toolsSdk
// The SDK renamed its registry export after 0.2.1-rc.3.
const ToolsService = toolsSdk.ToolsService ?? toolsSdk.ToolRuntime
import { apply, Config } from '../lib/index.js'

function registry(config) {
  // System-prompt assembly is outside this test; the real registry and Cordis
  // effects still own registration, schema projection, and definition lookup.
  const ctx = new Context().extend({ systemPrompt: { tools() {} } })
  const tools = new ToolsService(ctx)
  apply(ctx, Config(config))
  return tools
}
const exec = { signal: new AbortController().signal }

test('SDK registry exposes exactly five tools and validates arguments before launching worker', async () => {
  const tools = registry({ pythonExecutable: '/does/not/exist/python' })
  assert.deepEqual(tools.schemas().map(s => s.name), [
    'pdf_prepare', 'pdf_read_blocks', 'pdf_submit_translations', 'pdf_export', 'pdf_job_status',
  ])
  await assert.rejects(tools.get('pdf_prepare').execute({ path: 'paper.pdf' }, exec), ToolArgsError)
  await assert.rejects(tools.get('pdf_submit_translations').execute({
    jobId: 'test', version: 'v', translations: [{ blockId: 'b', text: 'x', extra: true }],
  }, exec), ToolArgsError)
  const result = await tools.get('pdf_job_status').execute({ jobId: 'test' }, exec)
  assert.equal(result.code, 'DEPENDENCY_MISSING')
  assert.deepEqual(validateJsonSchemaValue(tools.get('pdf_job_status').output.schema, result), [])
})

test('registered SDK tools perform prepare/read/submit/export/status with persisted worker state', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'pdf-registration-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  const tools = registry({
    workDirectory: join(directory, 'work'), outputDirectory: join(directory, 'output'),
    allowedInputDirectories: [resolve('examples')],
  })
  async function call(name, args) {
    const definition = tools.get(name)
    const result = await definition.execute(args, exec)
    assert.deepEqual(validateJsonSchemaValue(definition.output.schema, result), [], `${name} output contract`)
    assert.equal(definition.output.render(args, result)[0].text, JSON.stringify(result))
    assert.equal(result.ok, true, JSON.stringify(result))
    return result
  }
  const prepared = await call('pdf_prepare', { path: resolve('examples/synthetic-paper.pdf'), targetLanguage: 'en' })
  const jobId = prepared.jobId
  let cursor = 0
  const translations = []
  do {
    const batch = await call('pdf_read_blocks', { jobId, cursor, limit: 2 })
    // Identity text deliberately tests the interface, not translation quality.
    translations.push(...batch.data.blocks.map(b => ({ blockId: b.blockId, text: b.text })))
    cursor = batch.data.nextCursor
  } while (cursor !== null)
  assert.ok(translations.length > 2)
  await call('pdf_submit_translations', { jobId, version: prepared.data.version, translations })
  const exported = await call('pdf_export', { jobId })
  await access(exported.data.outputs['translated.pdf'])
  const status = await call('pdf_job_status', { jobId })
  assert.equal(status.data.state, 'COMPLETED')
})
