import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/pages/chat/component/research-detail/search-results.tsx', import.meta.url), 'utf8')
const exports = {}
const jsx = (type, props) => ({ type, props })
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  esModuleInterop: true,
} }).outputText, { exports, URL, require(name) {
  if (name.endsWith('.scss')) return {}
  if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx }
  if (name === '@ant-design/icons') return { FileTextOutlined: 'icon' }
  throw new Error(name)
} })

test('source URLs allow only absolute HTTP(S) links', () => {
  assert.equal(exports.getSourceUrl(' https://example.com/article '), 'https://example.com/article')
  for (const value of ['', undefined, 'javascript:alert(1)', 'file:///private', '/missing', 'not a link']) {
    assert.equal(exports.getSourceUrl(value), undefined)
  }
})

test('results use native new-tab links and missing URLs are explicitly labelled', () => {
  const tree = exports.default({ data: [
    { id: '1', title: 'Article', source: 'web', url: 'https://example.com/article' },
    { id: '2', title: 'No source', source: 'web' },
  ] })
  const [link, missing] = tree.props.children
  assert.equal(link.type, 'a')
  assert.equal(link.props.href, 'https://example.com/article')
  assert.equal(link.props.target, '_blank')
  assert.equal(link.props.rel, 'noopener noreferrer')
  assert.equal(missing.type, 'div')
  assert.equal(missing.props.href, undefined)
  assert.match(JSON.stringify(missing), /暂无原文链接/)
})
