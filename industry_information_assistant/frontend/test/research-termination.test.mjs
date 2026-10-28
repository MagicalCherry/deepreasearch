import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

// Exercise the actual handlers with controlled IO, without starting paid model calls.
const source = ts.createSourceFile('chat.tsx', fs.readFileSync(new URL('../src/pages/chat/index.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const nodes = []
function visit(node) { nodes.push(node); ts.forEachChild(node, visit) }
visit(source)
function handler(name, scope) {
  const node = nodes.find(node => ts.isVariableDeclaration(node) && node.name.getText(source) === name)
  return evaluate(node.initializer.arguments[0], scope)
}
function evaluate(node, scope) {
  const text = ts.createPrinter().printNode(ts.EmitHint.Unspecified, node, source)
  const js = ts.transpileModule(`const fn = ${text}; fn;`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return vm.runInNewContext(js, scope)
}
function refs() {
  return {
    console: { log() {}, error() {} }, id: 'session', terminationKey: 'stop:session',
    terminatedRef: { current: false }, drainingRef: { current: false },
    loadingRef: { current: true }, terminationState: 'idle',
    sessionStorage: { setItem() {} }, setTerminationState() {},
    setResearchSteps(update) { update([]) },
  }
}

test('stop freezes UI before cancel API returns and repeated clicks are idempotent', async () => {
  let resolve
  let requests = 0
  let cancelledReader = false
  const scope = { ...refs(), chat: { list: [{ loading: true, content: 'partial' }] },
    readerRef: { current: { cancel() { cancelledReader = true } } },
    api: { session: { cancelResearch() { requests++; return new Promise(r => { resolve = r }) } } },
  }
  const stop = handler('handleStop', scope)
  const pending = stop()
  assert.equal(scope.chat.list[0].loading, false)
  assert.match(scope.chat.list[0].content, /已终止/)
  assert.equal(scope.terminatedRef.current, true)
  assert.equal(cancelledReader, false)
  await stop()
  assert.equal(requests, 1)
  resolve()
  await pending
})

test('an in-flight checkpoint response cannot restart a stopped message', async () => {
  let resolve
  let restored = false
  const scope = { ...refs(), hasLoadedMessages: { current: true }, requestInFlightRef: { current: false },
    runGenerationRef: { current: 1 }, disposed: false, finished: false,
    setTimeout() { return 1 }, setResearchSteps() { restored = true },
    api: { session: { getFullResearchCheckpoint() { return new Promise(r => { resolve = r }) } } },
  }
  const node = nodes.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'loadCheckpoint')
  const load = evaluate(node, scope)
  const pending = load()
  scope.terminatedRef.current = true
  resolve({ data: { success: true, checkpoint: { status: 'running' } } })
  await pending
  assert.equal(restored, false)
})

test('queued question waits for drain then dispatches one item in FIFO order', async () => {
  const scope = { ...refs(), id: 'session', queueSession: 'session', historySession: 'session',
    loading: false, loadingRef: { current: false }, requestInFlightRef: { current: false },
    queueKey: 'queue', queuedQuestions: [{ text: 'first', modes: ['web'] }, { text: 'second', modes: [] }],
    deviceState: { searchModes: [] }, setQueuedQuestions(value) { scope.remaining = value },
    sendRef: { current: async text => { scope.sent = text } },
    message: { error() { throw new Error('unexpected send failure') } },
  }
  const node = nodes.find(node => ts.isCallExpression(node) && node.expression.getText(source) === 'useEffect'
    && node.arguments[0]?.getText(source).includes('const [next, ...remaining]'))
  const dispatch = evaluate(node.arguments[0], scope)
  scope.drainingRef.current = true
  dispatch()
  assert.equal(scope.sent, undefined)
  scope.drainingRef.current = false
  dispatch()
  assert.equal(scope.sent, 'first')
  assert.equal(scope.remaining[0].text, 'second')
  await Promise.resolve()
})
