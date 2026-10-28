import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

                               
                          
                   
                          
                        
 
                                                                                              
                         
             
              
                 
                
                 
                    
                    
                 
 
const failure = (code        , message        , retryable = false)         => ({
  ok: false, code, message, pages: [], retryable,
  nextAction: 'stop_and_inform_user', data: { canTranslate: false, canExport: false },
})

/** One bounded, cancellable JSON request per subprocess. No shell or user-controlled script. */
export function runWorker(tool        , args         , config              , signal              )                  {
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
    let stopped                    
    let settled = false
    let forceTimer                                           
    const finish = (result        ) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (forceTimer) clearTimeout(forceTimer)
      signal?.removeEventListener('abort', abort)
      resolve(result)
    }
    const stop = (result        ) => {
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
    child.on('error', () => finish(failure('DEPENDENCY_MISSING', 'Could not start configured Python executable. Check pythonExecutable and Python installation.')))
    child.stdin.on('error', () => { /* close/error events produce a structured result */ })
    child.stdout.on('data', (chunk        ) => {
      if (stopped) return
      if (output.length + chunk.length > config.maxResponseBytes) {
        stop(failure('RESPONSE_TOO_LARGE', 'PDF worker response exceeded configured byte limit.'))
      } else output = Buffer.concat([output, chunk])
    })
    // Consume diagnostics without logging paper text, environment values or secrets.
    child.stderr.on('data', (chunk        ) => {
      stderrBytes += chunk.length
      if (stderrBytes > config.maxResponseBytes) stop(failure('WORKER_FAILED', 'PDF worker diagnostic output exceeded configured limit.'))
    })
    child.on('close', code => {
      if (stopped) return finish(stopped)
      if (code !== 0) return finish(failure('WORKER_FAILED', `PDF worker exited with code ${code ?? 'unknown'}.`))
      try {
        const result = JSON.parse(output.toString('utf8'))          
        if (!result || typeof result !== 'object' || typeof result.ok !== 'boolean' ||
            typeof result.code !== 'string' || typeof result.message !== 'string' ||
            !Array.isArray(result.pages) || !result.pages.every(p => Number.isInteger(p) && p > 0) ||
            typeof result.retryable !== 'boolean' || typeof result.nextAction !== 'string' ||
            !Object.hasOwn(result, 'data')) throw new Error('invalid envelope')
        finish(result)
      } catch {
        finish(failure('WORKER_PROTOCOL_ERROR', 'PDF worker returned invalid structured output.'))
      }
    })
    child.stdin.end(request)
  })
}
