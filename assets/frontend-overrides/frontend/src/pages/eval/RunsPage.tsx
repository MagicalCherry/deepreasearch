// 评测运行：发起一次评测、看进度和汇总；点一行在右侧抽屉里看逐题结果和单题过程
import { CaretRightOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, InputNumber, Progress, Segmented, Select, Table, Tag } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import * as api from './api'
import { Lanes, Outcome } from './Lanes'
import type { Dataset, Item, ItemDetail, Question, RunInfo, Summary, Version } from './types'

const pct = (x?: number | null) => (x == null ? '—' : `${x.toFixed(1)}%`)
const STATE: Record<string, { text: string; color: string }> = {
  running: { text: '进行中', color: 'processing' },
  done: { text: '已完成', color: 'success' },
  stopped: { text: '已停止', color: 'warning' },
  interrupted: { text: '中断', color: 'error' },
}

function StateTag({ r }: { r: RunInfo }) {
  const st = r.status.state ?? ''
  const s = st === 'done' && !r.summary ? { text: '判分中', color: 'processing' } : STATE[st] ?? { text: st || '—', color: 'default' }
  return (
    <Tag color={s.color}>
      {s.text}
      {r.status.reason ? `（${r.status.reason}）` : ''}
    </Tag>
  )
}

export function SummaryCards({ s }: { s: Summary }) {
  const cells: [string, string, string?][] = [
    ['准确率', pct(s.accuracy), `${s.correct} / ${s.n}`],
    ['证据召回', pct(s.recall)],
    ['校准误差', s.calibration_error.toFixed(1)],
    ['运行出错', String(s.runner_errors)],
    ['平均搜索', s.avg_search.toFixed(1), '次 / 题'],
    ['平均读文档', s.avg_read.toFixed(1), '次 / 题'],
    ['平均 token', `${Math.round(s.avg_prompt_tokens / 1000)}k`, `输出 ${Math.round(s.avg_completion_tokens / 1000)}k`],
    ['平均耗时', `${s.avg_seconds.toFixed(0)}s`],
  ]
  return (
    <div className="metric-grid">
      {cells.map(([label, value, sub]) => (
        <div key={label} className={label === '运行出错' && s.runner_errors ? 'is-warn' : ''}>
          <span>{label}</span>
          <b>{value}</b>
          {sub && <small>{sub}</small>}
        </div>
      ))}
    </div>
  )
}

export function RunsPage({ versions, datasets }: { versions: Version[]; datasets: Dataset[] }) {
  const [list, setList] = useState<RunInfo[]>([])
  const [form, setForm] = useState({ dataset: '', version: '', concurrency: 6 })
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [dsFilter, setDsFilter] = useState<string>('全部')
  const refresh = () => api.runs().then(setList).catch((e) => setMsg({ type: 'error', text: String(e.message || e) }))

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    setForm((f) => ({
      ...f,
      version: f.version || versions[versions.length - 1]?.id || '',
      dataset: f.dataset || datasets[0]?.name || '',
    }))
  }, [versions, datasets])

  async function start() {
    setMsg(null)
    try {
      const { run_id } = await api.startRun(form)
      setMsg({ type: 'success', text: `已发起 ${run_id}` })
      setOpen(run_id)
      refresh()
    } catch (e: any) {
      setMsg({ type: 'error', text: String(e.message || e) })
    }
  }

  const names = useMemo(() => ['全部', ...Array.from(new Set(list.map((r) => r.config.dataset).filter(Boolean) as string[]))], [list])
  const rows = dsFilter === '全部' ? list : list.filter((r) => r.config.dataset === dsFilter)
  const current = list.find((r) => r.run_id === open)

  return (
    <div className="eval-stack">
      <section className="eval-card">
        <div className="eval-form">
          <label className="eval-field" style={{ width: 220 }}>
            <span>题集</span>
            <Select
              value={form.dataset || undefined}
              onChange={(v) => setForm({ ...form, dataset: v })}
              options={datasets.map((d) => ({ value: d.name, label: `${d.name}（${d.n} 题）${d.source === 'uploaded' ? ' · 上传' : ''}` }))}
            />
          </label>
          <label className="eval-field" style={{ width: 260 }}>
            <span>Agent 版本</span>
            <Select value={form.version || undefined} onChange={(v) => setForm({ ...form, version: v })} options={versions.map((v) => ({ value: v.id, label: `${v.id} · ${v.label}` }))} />
          </label>
          <label className="eval-field" style={{ width: 96 }}>
            <span>并发</span>
            <InputNumber min={1} max={16} value={form.concurrency} onChange={(v) => setForm({ ...form, concurrency: Number(v) || 1 })} style={{ width: '100%' }} />
          </label>
          <div className="eval-field eval-field--grow eval-field--end">
            <Button type="primary" icon={<CaretRightOutlined />} onClick={start} disabled={!form.version || !form.dataset}>
              发起评测
            </Button>
          </div>
        </div>
        {msg && <Alert style={{ marginTop: 12 }} type={msg.type} showIcon closable message={msg.text} onClose={() => setMsg(null)} />}
      </section>

      <section className="eval-card eval-card--flush">
        <div className="eval-card__head">
          <h3>历史运行</h3>
          {names.length > 2 && <Segmented size="small" value={dsFilter} onChange={(v) => setDsFilter(String(v))} options={names} />}
        </div>
        <Table<RunInfo>
          size="middle"
          rowKey="run_id"
          dataSource={rows}
          pagination={rows.length > 15 ? { pageSize: 15, showSizeChanger: false } : false}
          onRow={(r) => ({ onClick: () => setOpen(r.run_id) })}
          rowClassName={() => 'is-clickable'}
          locale={{ emptyText: '还没有运行' }}
          scroll={{ x: 900 }}
          columns={[
            // 运行名很长：一行显示，放不下截断，悬停看全名；窄屏时表格横向滚动而不是把名字折成四行
            { title: '运行', dataIndex: 'run_id', ellipsis: { showTitle: true }, render: (v) => <span className="eval-mono" title={v}>{v}</span> },
            { title: '版本', render: (_, r) => <span title={r.config.version}>{r.config.version}</span>, width: 120, ellipsis: true },
            { title: '题集', render: (_, r) => r.config.dataset, width: 110 },
            { title: '状态', render: (_, r) => <StateTag r={r} />, width: 110 },
            {
              title: '进度',
              width: 150,
              render: (_, r) => {
                const total = r.status.total ?? r.config.n ?? 0
                const done = r.status.done ?? 0
                return <Progress percent={total ? Math.round((100 * done) / total) : 0} size="small" format={() => `${done}/${total}`} />
              },
            },
            { title: '准确率', align: 'right', width: 90, render: (_, r) => <b>{pct(r.summary?.accuracy)}</b>, sorter: (a, b) => (a.summary?.accuracy ?? -1) - (b.summary?.accuracy ?? -1) },
            { title: '召回', align: 'right', width: 80, render: (_, r) => pct(r.summary?.recall) },
            { title: '校准误差', align: 'right', width: 90, render: (_, r) => (r.summary ? r.summary.calibration_error.toFixed(1) : '—') },
            { title: '出错', align: 'right', width: 70, render: (_, r) => r.summary?.runner_errors ?? r.status.errors ?? 0 },
          ]}
        />
      </section>

      <Drawer open={!!current} onClose={() => setOpen(null)} width="min(1280px, 92vw)" title={current && <RunTitle r={current} />} destroyOnClose>
        {current && <RunDetail r={current} />}
      </Drawer>
    </div>
  )
}

function RunTitle({ r }: { r: RunInfo }) {
  return (
    <span className="run-title">
      <span className="eval-mono">{r.run_id}</span>
      <StateTag r={r} />
    </span>
  )
}

function RunDetail({ r }: { r: RunInfo }) {
  const [rows, setRows] = useState<Item[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [only, setOnly] = useState<string>('全部')
  useEffect(() => {
    api.items(r.run_id).then(setRows).catch(() => setRows([]))
  }, [r.run_id, r.status.done, r.summary])
  const total = r.status.total ?? r.config.n ?? 0
  const shown = rows.filter((it) => only === '全部' || (only === '答对' ? it.correct === true : only === '答错' ? it.correct === false : !!it.error))
  const note = (it: Item) => (it.error ? '运行出错' : it.stop_reason === 'time_budget' ? '时间预算收住' : it.stop_reason === 'search_budget' ? '搜索预算收住' : '')

  return (
    <div className="eval-stack">
      <div className="eval-muted">
        {r.config.version} · {r.config.dataset} · 完成 {r.status.done ?? 0} / {total} · 出错 {r.status.errors ?? 0} · 并发 {r.config.concurrency ?? '—'} · 提交 {r.config.git_commit ?? '—'}
      </div>
      {r.summary && <SummaryCards s={r.summary} />}

      <div className="run-split">
        <div className="run-split__list">
          <Segmented size="small" value={only} onChange={(v) => setOnly(String(v))} options={['全部', '答对', '答错', '出错']} style={{ marginBottom: 8 }} />
          <Table<Item>
            size="small"
            rowKey="query_id"
            dataSource={shown}
            pagination={false}
            scroll={{ y: 'calc(100vh - 380px)' }}
            onRow={(it) => ({ onClick: () => setSel(it.query_id) })}
            rowClassName={(it) => 'is-clickable' + (it.query_id === sel ? ' is-selected' : '')}
            columns={[
              { title: '题号', dataIndex: 'query_id', width: 64 },
              { title: '', width: 44, render: (_, it) => (it.correct == null ? '—' : it.correct ? <Tag color="success">对</Tag> : <Tag color="error">错</Tag>) },
              {
                title: '答案',
                ellipsis: true,
                render: (_, it) => (
                  <>
                    {it.exact_answer || '—'}
                    {note(it) && <span className="eval-muted"> · {note(it)}</span>}
                  </>
                ),
              },
              { title: '置信', dataIndex: 'confidence', width: 56, align: 'right', render: (v) => v ?? '—' },
              { title: '搜/读', width: 64, align: 'right', render: (_, it) => `${it.n_search}/${it.n_read}` },
              { title: '耗时', width: 64, align: 'right', render: (_, it) => `${Math.round(it.seconds)}s` },
            ]}
          />
        </div>
        <div className="run-split__detail">
          {sel ? <ItemView runId={r.run_id} qid={sel} dataset={r.config.dataset} compact /> : <div className="eval-empty">点左边的一道题，在这里看它的完整研究过程</div>}
        </div>
      </div>
    </div>
  )
}

type ItemViewProps = { runId: string; qid: string; dataset?: string; compact?: boolean }

export function ItemView(props: ItemViewProps) {
  // 切换题目或运行时重置详情，防止短暂展示上一题的标准答案。
  return <SavedItemView key={`${props.runId}/${props.qid}`} {...props} />
}

function SavedItemView({ runId, qid, dataset, compact }: ItemViewProps) {
  const [d, setD] = useState<ItemDetail | null>(null)
  const [err, setErr] = useState('')
  const [question, setQuestion] = useState<Question | null>(null)
  const [referenceNote, setReferenceNote] = useState('标准答案加载中…')
  useEffect(() => {
    let active = true
    setD(null)
    setErr('')
    api.item(runId, qid).then((value) => { if (active) setD(value) })
      .catch((e) => { if (active) setErr(String(e.message || e)) })
    return () => { active = false }
  }, [runId, qid])
  useEffect(() => {
    let active = true
    setQuestion(null)
    setReferenceNote('标准答案加载中…')
    async function loadReference() {
      try {
        const name = dataset || (await api.run(runId)).config.dataset
        if (!name) throw new Error('运行记录没有题集名称')
        const rows = await api.dataset(name)
        const found = rows.find((row) => String(row.query_id) === String(qid))
        if (active) {
          setQuestion(found ?? null)
          setReferenceNote(found ? '该题未提供标准答案' : '当前题集中未找到本题')
        }
      } catch (e: any) {
        if (active) setReferenceNote(`标准答案读取失败：${String(e.message || e)}`)
      }
    }
    // 仅在历史评测详情中读取题集；不修改response/events，不发送研究或模型请求。
    loadReference()
    return () => { active = false }
  }, [runId, qid, dataset])
  if (err) return <Alert type="warning" showIcon message={err} />
  if (!d) return <div className="eval-empty">加载中…</div>
  return (
    <div className="eval-stack">
      {d.error && <Alert type="error" showIcon message="运行出错" description={d.error} />}
      <section className="eval-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <b>第 {qid} 题 · 答案核对</b>
          {d.judge?.correct === true ? <Tag color="success">答对</Tag>
            : d.judge?.correct === false ? <Tag color="error">答错</Tag> : <Tag>未判分</Tag>}
        </div>
        <div className="eval-muted">原始题目</div>
        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, margin: '4px 0 14px' }}>
          {question?.query || d.events.find((event) => event.event === 'agent_start')?.task || '题目暂不可用'}
        </div>
        <div className="eval-muted">标准答案（题集提供）</div>
        <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', marginTop: 4 }}>
          {question?.answer ? <strong>{question.answer}</strong> : <span className="eval-muted">{referenceNote}</span>}
        </div>
      </section>
      <Outcome events={d.events} queryId={qid} />
      <Lanes events={d.events} queryId={qid} compact={compact} />
    </div>
  )
}
// checksum: lpf2-00T16 lpf2-01N5b lpf2-02Mb8 lpf2-03I96
/* generated: lpf2-04Nb0 lpf2-05N87 lpf2-062c9 lpf2-07Ra6 */
/* revision: lpf2-08Tae lpf2-09T99 lpf2-0aRe9 lpf2-0b709 */
// checksum: lpf2-0cX99 lpf2-0dS26 lpf2-0eKf5 lpf2-0fGe9
// checksum: lpf2-10B3f lpf2-11I80 lpf2-12209 lpf2-13N29
// checksum: lpf2-14Cf5 lpf2-15H4a lpf2-16X77 lpf2-17390
// checksum: lpf2-18W54 lpf2-19Y64
