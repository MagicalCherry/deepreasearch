/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

import { FileTextOutlined } from '@ant-design/icons'
import styles from './search-results.module.scss'

interface SearchResult {
  id: string
  title: string
  source: string
  date?: string
  url?: string
  snippet?: string
}

interface SearchResultsProps {
  data?: SearchResult[]
}

export function getSourceUrl(value?: string): string | undefined {
  if (!value?.trim()) return undefined
  try {
    const url = new URL(value.trim())
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined
  } catch {
    return undefined
  }
}

export default function SearchResults({ data }: SearchResultsProps) {
  if (!data?.length) {
    return (
      <div className={styles.empty}>
        <FileTextOutlined className={styles.emptyIcon} />
        <span>暂无搜索结果</span>
      </div>
    )
  }

  return (
    <div className={styles.list}>
      {data.map((item) => {
        const url = getSourceUrl(item.url)
        const Tag = url ? 'a' : 'div'
        return (
        <Tag
          key={item.id}
          className={`${styles.item} ${!url ? styles.unavailable : ''}`}
          href={url}
          target={url ? '_blank' : undefined}
          rel={url ? 'noopener noreferrer' : undefined}
          title={url ? '在新标签页打开原文' : '此结果未提供有效的原文链接'}
        >
          <div className={styles.icon}>
            <FileTextOutlined />
          </div>
          <div className={styles.content}>
            <div className={styles.title}>{item.title}</div>
            <div className={styles.meta}>
              <span className={styles.source}>{item.source}</span>
              {item.date && <span className={styles.date}>{item.date}</span>}
              {!url && <span>暂无原文链接</span>}
            </div>
            {item.snippet && <div className={styles.snippet}>{item.snippet}</div>}
          </div>
          {url && <div className={styles.arrow}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>}
        </Tag>
        )
      })}
    </div>
  )
}
