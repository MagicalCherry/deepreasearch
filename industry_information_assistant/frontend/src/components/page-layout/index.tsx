/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

import classNames from 'classnames'
import { PropsWithChildren, ReactNode, useState } from 'react'
import { Button, Tooltip } from 'antd'
import { DoubleLeftOutlined, DoubleRightOutlined, ExpandAltOutlined, ShrinkOutlined } from '@ant-design/icons'
import './index.scss'

export default function ComPageLayout(
  props: PropsWithChildren<{
    className?: string
    right?: ReactNode
    sender?: ReactNode
    wideRight?: boolean  // 宽右侧面板模式（1/3 左 + 2/3 右）
  }>,
) {
  const { children, className, right, sender, wideRight, ...rest } = props
  const [panelMode, setPanelMode] = useState<'normal' | 'expanded' | 'collapsed'>('normal')
  const collapsed = wideRight && panelMode === 'collapsed'
  return (
    <div className={classNames('com-page-layout', className, {
      'wide-right-mode': wideRight,
      'right-panel-collapsed': collapsed,
      'right-panel-expanded': wideRight && panelMode === 'expanded',
    })} {...rest}>
      <div className="com-page-layout__main">
        <div className="com-page-layout__main-content">{children}</div>

        <div className="com-page-layout__sender">{sender}</div>
      </div>
      {right ? <aside className="com-page-layout__right" aria-label="研究过程面板">
        {wideRight && <div className="com-page-layout__panel-toolbar">
          {!collapsed && <span>研究过程</span>}
          <div className="com-page-layout__panel-actions">
            {!collapsed && <Tooltip title={panelMode === 'expanded' ? '恢复面板宽度' : '放大研究面板'}>
              <Button type="text" size="small" aria-label={panelMode === 'expanded' ? '恢复面板宽度' : '放大研究面板'}
                icon={panelMode === 'expanded' ? <ShrinkOutlined /> : <ExpandAltOutlined />}
                onClick={() => setPanelMode(panelMode === 'expanded' ? 'normal' : 'expanded')} />
            </Tooltip>}
            <Tooltip title={collapsed ? '展开研究面板' : '收起研究面板'}>
              <Button type="text" size="small" aria-label={collapsed ? '展开研究面板' : '收起研究面板'}
                aria-expanded={!collapsed} aria-controls="research-panel-content"
                icon={collapsed ? <DoubleLeftOutlined /> : <DoubleRightOutlined />}
                onClick={() => setPanelMode(collapsed ? 'normal' : 'collapsed')} />
            </Tooltip>
          </div>
        </div>}
        {collapsed && <span className="com-page-layout__collapsed-label" aria-hidden="true">研究过程</span>}
        <div id="research-panel-content" className="com-page-layout__panel-content" hidden={!!collapsed}>{right}</div>
      </aside> : null}
    </div>
  )
}
