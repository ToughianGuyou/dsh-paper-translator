                                                  
import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { resolve } from 'node:path'
import { runWorker,                   } from './bridge.js'

export const name = 'dsh-paper-translator'
export const inject = ['tools']
                                              
                               
                       
                         
                                   
                  
                  
                      
                      
 
export const Config                 = Schema.object({
  keepOriginalMarkdown: Schema.boolean().default(true),
  workDirectory: Schema.string().default('./work/dsh-paper-translator'),
  outputDirectory: Schema.string().default('./output/dsh-paper-translator'),
  allowedInputDirectories: Schema.array(Schema.string()).default(['.']),
  pythonExecutable: Schema.string().default('python3'),
  fontPath: Schema.string().default(''),
  maxPages: Schema.number().min(1).max(10000).step(1).default(300),
  maxFileBytes: Schema.number().min(1024).max(1073741824).step(1).default(104857600),
  maxBatchSize: Schema.number().min(1).max(100).step(1).default(20),
  timeoutMs: Schema.number().min(1000).max(3600000).step(1).default(120000),
  maxResponseBytes: Schema.number().min(4096).max(67108864).step(1).default(8388608),
})
const output = {
  schema: {
    type: 'object', additionalProperties: false,
    properties: {
      ok: { type: 'boolean', required: true },
      code: { type: 'string', required: true },
      message: { type: 'string', required: true },
      jobId: { type: 'string' },
      pages: { type: 'array', items: { type: 'integer' }, required: true },
      retryable: { type: 'boolean', required: true },
      nextAction: { type: 'string', required: true },
      data: { type: 'json', required: true },
    },
  },
  render: (_args         , value         ) => [{ type: 'text'         , text: JSON.stringify(value) }],
}         
const jobId = { type: 'string', required: true, description: 'Exact jobId returned by pdf_prepare.' }         
const stopRule = ' If ok=false or nextAction=stop_and_inform_user, stop and explain the code and page numbers to the user; do not submit translations or export a stopped job.'

export function apply(ctx         , provided        ) {
  const config         = {
    ...provided,
    nodeExecutable: process.execPath,
    workDirectory: resolve(provided.workDirectory),
    outputDirectory: resolve(provided.outputDirectory),
    allowedInputDirectories: provided.allowedInputDirectories.map(p => resolve(p)),
    fontPath: provided.fontPath ? resolve(provided.fontPath) : '',
  }
  if (!config.pythonExecutable.trim() || config.allowedInputDirectories.length === 0) {
    throw new Error('pythonExecutable and at least one allowedInputDirectories entry are required.')
  }
  ctx.tools.register(defineTool({
    name: 'html_prepare',
    description: 'Prepare an explicitly authorized local article HTML file or a versioned HTTPS arXiv/ar5iv /html/IDvN URL. Preserve original formula nodes and inline formatting; export translated HTML without PDF conversion. No scripts execute. Same read/submit/export/status tools handle the job. For remote sources tell the user to check version/completeness; never silently substitute for their PDF.' + stopRule,
    parameters: {
      path: { type: 'string', description: 'Authorized saved .html/.htm file inside allowed directories; provide path or url.' },
      url: { type: 'string', description: 'Explicitly authorized https://arxiv.org/html/IDvN or https://ar5iv.labs.arxiv.org/html/IDvN; version is required.' },
      targetLanguage: { type: 'string', required: true, description: 'Explicit user-selected translation language.' },
    }, output,
    execute: (args, exec) => runWorker('html_prepare', args, config, exec.signal),
  }))
  ctx.tools.register(defineTool({
    name: 'pdf_prepare',
    description: 'Inspect every page and prepare a text-layer PDF paper for translation. No OCR and no translation API calls. Ask the user for target language if absent. Only use a user-authorized PDF path inside configured allowed directories. Returns job summary, not the full paper.' + stopRule,
    parameters: {
      path: { type: 'string', required: true, description: 'User-authorized source PDF path; never modified.' },
      targetLanguage: { type: 'string', required: true, description: 'Explicit user-selected language, e.g. zh-CN or en.' },
    }, output,
    execute: (args, exec) => runWorker('pdf_prepare', args, config, exec.signal),
  }))
  ctx.tools.register(defineTool({
    name: 'pdf_read_blocks',
    description: 'Read a bounded ordered batch of blocks to translate. Translate fully without summarizing; keep every protected token exactly. Context-only neighbors must not be submitted. Resume from job status and only fill missing blocks.' + stopRule,
    parameters: { jobId, cursor: { type: 'integer', description: 'Zero-based batch cursor, default 0.' }, limit: { type: 'integer', description: 'Requested batch size, bounded by configured maxBatchSize.' } }, output,
    execute: (args, exec) => runWorker('pdf_read_blocks', args, config, exec.signal),
  }))
  ctx.tools.register(defineTool({
    name: 'pdf_submit_translations',
    description: 'Submit complete translations by stable blockId using the exact version returned by prepare/read/status. Preserve all protected placeholders with the same spelling and counts. Translate only returned eligible blocks; HTML captions and table cells are eligible, preserved references and metadata are not. Do not proceed after rejected submission.' + stopRule,
    parameters: {
      jobId, version: { type: 'string', required: true, description: 'Current job version returned by the worker.' },
      translations: { type: 'array', required: true, items: { type: 'object', additionalProperties: false, properties: {
        blockId: { type: 'string', required: true }, text: { type: 'string', required: true },
      } } },
    }, output,
    execute: (args, exec) => runWorker('pdf_submit_translations', args, config, exec.signal),
  }))
  ctx.tools.register(defineTool({
    name: 'pdf_export', description: 'After all translations are accepted, export translated.html for HTML jobs, or validate and reflow a translated PDF for PDF jobs. Only deliver returned final paths after ok=true. Do not claim semantic translation accuracy from structural validation.' + stopRule,
    parameters: { jobId }, output,
    execute: (args, exec) => runWorker('pdf_export', args, config, exec.signal),
  }))
  ctx.tools.register(defineTool({
    name: 'pdf_job_status', description: 'Inspect persisted progress, version, missing blocks, stop reasons and validated output paths after interruptions.' + stopRule,
    parameters: { jobId }, output,
    execute: (args, exec) => runWorker('pdf_job_status', args, config, exec.signal),
  }))
}
