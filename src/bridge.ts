import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export interface WorkerConfig {
  pythonExecutable: string
  timeoutMs: number
  maxResponseBytes: number
  [key: string]: unknown
}
type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }
export interface Result {
  ok: boolean
  code: string
  message: string
  jobId?: string
  pages: number[]
  retryable: boolean
  nextAction: string
  data: JsonValue
}
const failure = (code: string, message: string, retryable = false): Result => ({
  ok: false, code, message, pages: [], retryable,
  nextAction: 'stop_and_inform_user', data: { canTranslate: false, canExport: false },
})

function pythonFailure(code: string, message: string, config: WorkerConfig): Result {
  const result = failure(code, `${message} Configured pythonExecutable: ${JSON.stringify(config.pythonExecutable)}. Check that cordis.patch.yml uses id: dsh-paper-translator (the old dsh-pdf-paper-translation-tools id does not configure this plugin). On Windows, run py -3.12 -c "import sys; print(sys.executable)" and set pythonExecutable to that real Python path, not the WindowsApps Store alias. Restart DSH after changing configuration.`)
  result.data = { canTranslate: false, canExport: false, configuredPythonExecutable: config.pythonExecutable, expectedPluginId: 'dsh-paper-translator' }
  return result
}

/** One bounded, cancellable JSON request per subprocess. No shell or user-controlled script. */
export function runWorker(tool: string, args: unknown, config: WorkerConfig, signal?: AbortSignal): Promise<Result> {
  if (signal?.aborted) return Promise.resolve(failure('CANCELLED', 'PDF operation cancelled.'))
  const request = JSON.stringify({ tool, args, config })
  if (Buffer.byteLength(request) > config.maxResponseBytes) {
    return Promise.resolve(failure('REQUEST_TOO_LARGE', 'Submit fewer or shorter blocks per batch.'))
  }
  return new Promise(resolve => {
    const workerPath = fileURLToPath(new URL('../python/worker.py', import.meta.url))
    const child = spawn(config.pythonExecutable, ['-u', workerPath], {
      shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    })
    let output = Buffer.alloc(0)
    let stderrBytes = 0
    let stopped: Result | undefined
    let settled = false
    let forceTimer: ReturnType<typeof setTimeout> | undefined
    const finish = (result: Result) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (forceTimer) clearTimeout(forceTimer)
      signal?.removeEventListener('abort', abort)
      resolve(result)
    }
    const stop = (result: Result) => {
      if (stopped || settled) return
      stopped = result
      child.kill('SIGTERM')
      forceTimer = setTimeout(() => child.kill('SIGKILL'), 1500)
      forceTimer.unref()
    }
    const abort = () => stop(failure('CANCELLED', 'PDF operation cancelled. Check job status before resuming.'))
    const timer = setTimeout(() => stop(failure('WORKER_TIMEOUT', 'PDF worker exceeded configured timeout; inspect job status before retrying.', true)), config.timeoutMs)
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) abort()
    child.on('error', () => finish(pythonFailure('DEPENDENCY_MISSING', 'Could not start Python.', config)))
    child.stdin.on('error', () => { /* close/error events produce a structured result */ })
    child.stdout.on('data', (chunk: Buffer) => {
      if (stopped) return
      if (output.length + chunk.length > config.maxResponseBytes) {
        stop(failure('RESPONSE_TOO_LARGE', 'PDF worker response exceeded configured byte limit.'))
      } else output = Buffer.concat([output, chunk])
    })
    // Consume diagnostics without logging paper text, environment values or secrets.
    child.stderr.on('data', (chunk: Buffer) => {
      stderrBytes += chunk.length
      if (stderrBytes > config.maxResponseBytes) stop(failure('WORKER_FAILED', 'PDF worker diagnostic output exceeded configured limit.'))
    })
    child.on('close', code => {
      if (stopped) return finish(stopped)
      if (code !== 0) return finish(pythonFailure('WORKER_FAILED', `Python worker exited with code ${code ?? 'unknown'}.`, config))
      try {
        const result = JSON.parse(output.toString('utf8')) as Result
        if (!result || typeof result !== 'object' || typeof result.ok !== 'boolean' ||
            typeof result.code !== 'string' || typeof result.message !== 'string' ||
            !Array.isArray(result.pages) || !result.pages.every(p => Number.isInteger(p) && p > 0) ||
            typeof result.retryable !== 'boolean' || typeof result.nextAction !== 'string' ||
            !Object.hasOwn(result, 'data')) throw new Error('invalid envelope')
        finish(result)
      } catch {
        finish(pythonFailure('WORKER_PROTOCOL_ERROR', 'Python worker returned invalid structured output; the configured command may not be a working Python interpreter.', config))
      }
    })
    child.stdin.end(request)
  })
}
