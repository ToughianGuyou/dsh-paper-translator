import { stripTypeScriptTypes } from 'node:module'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
await mkdir(new URL('../lib/', import.meta.url), { recursive: true })
for (const name of ['index', 'bridge']) {
  const source = await readFile(new URL(`../src/${name}.ts`, import.meta.url), 'utf8')
  const js = stripTypeScriptTypes(source, { mode: 'strip' })
  await writeFile(new URL(`../lib/${name}.js`, import.meta.url), js)
}
console.log('Built lib/index.js and lib/bridge.js (syntax stripping; use npm run typecheck for type checking).')
