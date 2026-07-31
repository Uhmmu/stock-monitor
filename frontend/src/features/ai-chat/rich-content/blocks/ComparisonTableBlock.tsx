import { useMemo, useState } from 'react'
import { BlockFrame } from '../components/BlockFrame'
import { formatCell, toNumber } from '../format'
import type { ComparisonTableData, RichBlockProps } from '../types'

export function ComparisonTableBlock({ block, citations, onCitation }: RichBlockProps<ComparisonTableData>) {
  const initial = block.data.default_sort_key && block.data.columns.some(column => column.key === block.data.default_sort_key)
    ? block.data.default_sort_key
    : null
  const [sort, setSort] = useState<{ key: string; direction: 1 | -1 } | null>(initial ? { key: initial, direction: -1 } : null)
  const rows = useMemo(() => {
    if (!sort) return block.data.rows
    return [...block.data.rows].sort((left, right) => {
      const a = left.values[sort.key]
      const b = right.values[sort.key]
      const an = toNumber(typeof a === 'number' || typeof a === 'string' ? a : null)
      const bn = toNumber(typeof b === 'number' || typeof b === 'string' ? b : null)
      const result = an != null && bn != null
        ? an - bn
        : String(a ?? '').localeCompare(String(b ?? ''), 'zh-CN')
      return result * sort.direction
    })
  }, [block.data.rows, sort])

  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <div className="ai-rich-comparison" role="region" aria-label="比较表格" tabIndex={0}>
      <table>
        <thead><tr>
          <th>项目</th>
          {block.data.columns.map(column => <th key={column.key}>
            {column.sortable ? <button onClick={() => setSort(current => current?.key === column.key ? { key: column.key, direction: current.direction === 1 ? -1 : 1 } : { key: column.key, direction: -1 })}>
              {column.label}<span aria-hidden="true">{sort?.key === column.key ? sort.direction === 1 ? ' ↑' : ' ↓' : ' ↕'}</span>
            </button> : column.label}
          </th>)}
        </tr></thead>
        <tbody>{rows.map(row => <tr key={row.row_id} className={row.row_id === block.data.highlight_row_id ? 'highlight' : ''}>
          <th>{row.label}{row.symbol && row.symbol !== row.label && <small>{row.symbol}</small>}</th>
          {block.data.columns.map(column => <td key={column.key} data-label={column.label}>{formatCell(row.values[column.key], column.value_type)}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  </BlockFrame>
}
