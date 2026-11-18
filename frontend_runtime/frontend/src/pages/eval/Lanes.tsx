// 研究过程泳道：每个 Agent 一栏，按时间排它做的事。研究台、评测详情、同题对照共用。
import { Segmented, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { DocLink } from './DocContext'
import type { Ev } from './types'

const ROLE_ORDER = (a: string) => (a === 'planner' ? 0 : a.startsWith('scout') || a === 'agent' ? 1 : a === 'writer' ? 2 : a === 'critic' ? 3 : 4)
const AGENT_NAME: Record<string, string> = { planner: '规划', writer: '报告撰写', critic: '审核', agent: '单 Agent', answer: '最终作答', scout: '侦探阶段', 'scout-sup': '补充搜索' }
export const agentName = (a: string) => AGENT_NAME[a] ?? (a.startsWith('scout-') ? `侦探 ${a.slice(6)}` : a)
const KIND: Record<string, string> = { agent_start: '开始', plan: '计划', search: '搜索', read: '读文档', fact: '事实', verify: '核查', answer: '答案' }
const roleOf = (a: string) => (a.startsWith('scout') || a === 'agent' ? 'scout' : a)

export function lanesOf(events: Ev[]) {
  const lanes = new Map<string, Ev[]>()
  const multi = events.some((e) => e.agent === 'planner' || e.agent.startsWith('scout-'))
  for (const e of events) {
    if (e.event === 'done' || e.event === 'error') continue
    // 原始记录不改写：多角色研究的公共答案归入最终作答，裸scout仅展示实际补搜。
    const lane = multi && e.agent === 'agent' && e.event === 'answer' ? 'answer'
      : e.agent === 'scout' ? 'scout-sup' : e.agent
    if (!lanes.has(lane)) lanes.set(lane, [])
    lanes.get(lane)!.push(e)
  }
  return [...lanes.entries()]
    .filter(([a, evs]) => a !== 'scout-sup' || evs.some((e) => e.event !== 'agent_start'))
    .map(([a, evs]): [string, Ev[]] => [a, [...evs].sort((x, y) => x.t - y.t)])
    .sort((a, b) => ROLE_ORDER(a[0]) - ROLE_ORDER(b[0]) || a[0].localeCompare(b[0], 'en', { numeric: true }))
}

const words = (q: string) => q.split(/\W+/).filter((w) => w.length > 2)

export function EventCard({ e, queryId }: { e: Ev; queryId?: string }) {
  return (
    <div className={`lane-ev lane-ev--${e.event}`}>
      <div className="lane-ev__head">
        <span className="lane-ev__kind">{KIND[e.event] ?? e.event}</span>
        <span className="lane-ev__t">{e.t.toFixed(1)}s</span>
      </div>
      {e.event === 'agent_start' && <div className="lane-ev__body">
        {(e.agent === 'writer' || e.agent === 'critic' || e.agent === 'answer') ? <>
          <div>{e.agent === 'writer' ? '开始撰写或修订报告' : e.agent === 'critic' ? '开始审核报告' : '开始从报告和事实中提取答案'}</div>
          <details><summary>查看原始问题</summary>{e.task}</details>
        </> : e.task}
      </div>}
      {e.event === 'plan' && (
        <ul className="lane-ev__list">
          {(e.items as string[]).slice(0, 12).map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      )}
      {e.event === 'search' && (
        <div className="lane-ev__body">
          <code className="lane-ev__query">{e.query}</code>
          {(e.results as { docid: string; title: string }[]).slice(0, 5).map((h) => (
            <div className="lane-ev__hit" key={h.docid}>
              <DocLink docid={h.docid} terms={words(e.query)} queryId={queryId} />
              <span>{h.title}</span>
            </div>
          ))}
          {e.results.length === 0 && <div className="eval-muted">零命中</div>}
        </div>
      )}
      {e.event === 'read' && (
        <div className="lane-ev__body">
          <div className="lane-ev__hit">
            <DocLink docid={e.docid} queryId={queryId} />
            <span>{e.title}</span>
          </div>
          {e.span && <div className="eval-muted">{e.span}</div>}
        </div>
      )}
      {e.event === 'fact' && (
        <div className="lane-ev__body">
          {e.text} {e.docid && <DocLink docid={e.docid} queryId={queryId} />}
        </div>
      )}
      {e.event === 'verify' && (
        <div className="lane-ev__body">
          <Tag color={e.verdict === 'pass' ? 'success' : 'error'}>{e.verdict === 'pass' ? '通过' : '打回'}</Tag>
          {e.total > 0 && (
            <b>
              已验证 {e.verified}/{e.total}
            </b>
          )}
          <div className="eval-muted">{e.note}</div>
          {e.total === 0 && <div className="eval-muted">此记录未提供逐项约束核验结果，0/0不代表已完成验证。</div>}
        </div>
      )}
      {e.event === 'answer' && (
        <div className="lane-ev__body">
          <b>{e.exact_answer}</b>
          <span className="eval-muted"> 置信度 {e.confidence}%</span>
        </div>
      )}
    </div>
  )
}

function LaneBody({ evs, queryId }: { evs: Ev[]; queryId?: string }) {
  const writer = evs.some((e) => e.agent === 'writer')
  const critic = evs.some((e) => e.agent === 'critic')
  return (
    <>
      {writer && <div className="eval-muted" style={{ padding: '12px 16px' }}>这份运行记录未保存报告正文，无法展开查看。下方是已记录的阶段事件；最终答案请看“最终作答”。</div>}
      {critic && <div className="eval-muted" style={{ padding: '12px 16px' }}>这份运行记录仅保存审核汇总，未保存完整审核意见或具体修改建议。</div>}
      {evs.map((e, i) => (
        <EventCard key={i} e={e} queryId={queryId} />
      ))}
    </>
  )
}

/**
 * 两种排法：
 * - 默认：每个 Agent 一栏，横向并排，适合一整屏看一次研究；
 * - compact：一次只看一个 Agent，上面一排按钮切换。同题对照里左右各只有半屏，并排放不下，横向滚动条又在屏幕外面。
 */
export function Lanes({ events, queryId, compact }: { events: Ev[]; queryId?: string; compact?: boolean }) {
  const lanes = lanesOf(events)
  const [active, setActive] = useState<string>('')
  useEffect(() => {
    if (lanes.length && !lanes.some(([a]) => a === active)) setActive(lanes[0][0])
  }, [lanes, active])
  if (!lanes.length) return <div className="eval-empty">还没有事件</div>

  if (compact) {
    const cur = lanes.find(([a]) => a === active) ?? lanes[0]
    return (
      <div className="lane-tabs">
        <Segmented
          size="small"
          value={cur[0]}
          onChange={(v) => setActive(String(v))}
          options={lanes.map(([agent, evs]) => ({
            value: agent,
            label: (() => {
              const n = evs.filter((e) => e.event === 'search').length
              return n ? `${agentName(agent)} · ${n} 搜` : agentName(agent)
            })(),
          }))}
        />
        <section className={`lane lane--${roleOf(cur[0])} lane--single`}>
          <header>
            <span className="lane__name">{agentName(cur[0])}</span>
            <span className="lane__count">
              {cur[1].filter((e) => e.event === 'search').length} 搜 · {cur[1].filter((e) => e.event === 'read').length} 读
            </span>
          </header>
          <div className="lane__body">
            <LaneBody evs={cur[1]} queryId={queryId} />
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="lanes">
      {lanes.map(([agent, evs]) => (
        <section className={`lane lane--${roleOf(agent)}`} key={agent}>
          <header>
            <span className="lane__name">{agentName(agent)}</span>
            <span className="lane__count">
              {evs.filter((e) => e.event === 'search').length} 搜 · {evs.filter((e) => e.event === 'read').length} 读
            </span>
          </header>
          <div className="lane__body">
            <LaneBody evs={evs} queryId={queryId} />
          </div>
        </section>
      ))}
    </div>
  )
}

export function Outcome({ events, queryId }: { events: Ev[]; queryId?: string }) {
  const [open, setOpen] = useState(false)
  const ans = events.find((e) => e.event === 'answer')
  const done = events.find((e) => e.event === 'done')
  const err = events.find((e) => e.event === 'error')
  if (!ans && !done && !err) return null
  return (
    <section className="outcome">
      {err && <div className="outcome__error">研究出错：{err.message}</div>}
      {ans && (
        <>
          <div className="outcome__label">最终答案</div>
          <div className="outcome__answer">
            <strong>{ans.exact_answer || '（空）'}</strong>
            <Tag>置信度 {ans.confidence}%</Tag>
          </div>
          {/* 解释有时很长（模型把推理过程也写了进来）：默认收成三行，要看再展开 */}
          <p className={'outcome__why' + (open ? '' : ' is-clamped')}>{ans.explanation}</p>
          {String(ans.explanation || '').length > 220 && (
            <button className="outcome__more" onClick={() => setOpen(!open)}>
              {open ? '收起' : '展开全部'}
            </button>
          )}
          {ans.cited_docids?.length > 0 && (
            <div className="outcome__cited">
              <span>引用文档</span>
              {(ans.cited_docids as string[]).map((d) => (
                <DocLink key={d} docid={d} queryId={queryId} />
              ))}
            </div>
          )}
        </>
      )}
      {done && (
        <div className="outcome__usage">
          <span>搜索 {done.n_search} 次</span>
          <span>读文档 {done.n_read} 次</span>
          <span>
            token {done.usage.prompt_tokens.toLocaleString()} / {done.usage.completion_tokens.toLocaleString()}
          </span>
          <span>{done.seconds} 秒</span>
        </div>
      )}
    </section>
  )
}
/* revision: lpf2-00T16 lpf2-01N5b lpf2-02Mb8 lpf2-03I96 */
/* revision: lpf2-04Nb0 lpf2-05N87 lpf2-062c9 lpf2-07Ra6 */
/* generated: lpf2-08Tae lpf2-09T99 lpf2-0aRe9 lpf2-0b709 */
// checksum: lpf2-0cX99 lpf2-0dS26 lpf2-0eKf5 lpf2-0fGe9
// checksum: lpf2-10B3f lpf2-11I80 lpf2-12209 lpf2-13N29
// checksum: lpf2-14Cf5 lpf2-15H4a lpf2-16X77 lpf2-17390
/* generated: lpf2-18W54 lpf2-19Y64 */
