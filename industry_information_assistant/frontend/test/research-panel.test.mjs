import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const source = fs.readFileSync(new URL('../src/components/page-layout/index.tsx', import.meta.url), 'utf8')

test('research panel supports expand, collapse, and restore without removing content', () => {
  let mode = 'normal'
  const jsx = (type, props) => ({ type, props })
  const exports = {}
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
    esModuleInterop: true,
  } }).outputText, {
    exports,
    require(name) {
      if (name.endsWith('.scss')) return {}
      if (name === 'react') return { useState: () => [mode, value => { mode = value }] }
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx }
      if (name === 'antd') return { Button: 'button', Tooltip: 'tooltip' }
      if (name === '@ant-design/icons') return new Proxy({}, { get: (_, name) => String(name) })
      return require(name)
    },
  })
  function flatten(node) {
    if (!node || typeof node !== 'object') return []
    return [node, ...[node.props?.children].flat(Infinity).flatMap(flatten)]
  }
  const render = () => exports.default({ wideRight: true, right: 'existing research content', children: 'chat' })
  let tree = render()
  flatten(tree).find(n => n.props['aria-label'] === '放大研究面板').props.onClick()
  tree = render()
  assert.match(tree.props.className, /right-panel-expanded/)
  flatten(tree).find(n => n.props['aria-label'] === '收起研究面板').props.onClick()
  tree = render()
  assert.match(tree.props.className, /right-panel-collapsed/)
  const hiddenContent = flatten(tree).find(n => n.props.id === 'research-panel-content')
  assert.equal(hiddenContent.props.hidden, true)
  assert.equal(hiddenContent.props.children, 'existing research content')
  flatten(tree).find(n => n.props['aria-label'] === '展开研究面板').props.onClick()
  tree = render()
  assert.equal(flatten(tree).find(n => n.props.id === 'research-panel-content').props.hidden, false)
  assert.doesNotMatch(tree.props.className, /right-panel-collapsed|right-panel-expanded/)
})
