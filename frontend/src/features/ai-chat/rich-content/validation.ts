import type {
  RichBlock,
  RichContentDocument,
  RichContentPart,
} from './types'

export const MAX_RICH_PARTS = 41
export const MAX_RICH_BLOCKS = 10
export const MAX_RICH_DOCUMENT_CHARS = 100_000

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function isString(value: unknown, max = 10_000): value is string {
  return typeof value === 'string' && value.length <= max
}

export function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function optionalNumber(value: unknown): boolean {
  return value == null || isNumber(value)
}

export function stringArray(value: unknown, max: number, itemMax = 1_000): value is string[] {
  return Array.isArray(value) && value.length <= max && value.every(item => isString(item, itemMax))
}

export function recordArray(value: unknown, max: number): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length <= max && value.every(isRecord)
}

export function safePublicUrl(value: unknown): string | null {
  if (!isString(value, 2_000)) return null
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

function validBlock(value: unknown): value is RichBlock {
  if (!isRecord(value)) return false
  let dataSize = MAX_RICH_DOCUMENT_CHARS + 1
  try {
    dataSize = JSON.stringify(value.data).length
  } catch {
    return false
  }
  const freshness = value.freshness
  const validFreshness = freshness == null || (
    isRecord(freshness)
    && ['fresh', 'aging', 'stale', 'unknown'].includes(String(freshness.status))
    && (freshness.as_of == null || isString(freshness.as_of, 80))
    && (freshness.retrieved_at == null || isString(freshness.retrieved_at, 80))
    && (freshness.label == null || isString(freshness.label, 160))
  )
  return (
    isString(value.block_id, 128)
    && /^[A-Za-z][A-Za-z0-9_.:\-]*$/.test(value.block_id)
    && isString(value.block_type, 64)
    && Number.isInteger(value.block_version)
    && Number(value.block_version) >= 1
    && Number(value.block_version) <= 100
    && isRecord(value.data)
    && dataSize <= 30_000
    && stringArray(value.citation_keys, 100, 16)
    && stringArray(value.source_ids, 100, 256)
    && stringArray(value.warnings, 20, 500)
    && isString(value.fallback_markdown, 30_000)
    && validFreshness
  )
}

function validPart(value: unknown): value is RichContentPart {
  if (!isRecord(value) || !isString(value.part_id, 128)) return false
  if (value.type === 'markdown') return isString(value.content, MAX_RICH_DOCUMENT_CHARS)
  if (value.type === 'block') return validBlock(value.block)
  return false
}

export function validateRichContentDocument(value: unknown): RichContentDocument | null {
  if (!isRecord(value) || value.schema_version !== 1) return null
  if (
    !Array.isArray(value.parts)
    || value.parts.length > MAX_RICH_PARTS
    || !value.parts.every(validPart)
    || !isString(value.fallback_markdown, MAX_RICH_DOCUMENT_CHARS)
    || !stringArray(value.warnings ?? [], 40, 500)
  ) return null
  try {
    if (JSON.stringify(value).length > MAX_RICH_DOCUMENT_CHARS) return null
  } catch {
    return null
  }
  const partIds = value.parts.map(part => part.part_id)
  if (new Set(partIds).size !== partIds.length) return null
  const blockIds = value.parts
    .filter(part => part.type === 'block')
    .map(part => part.block.block_id)
  if (blockIds.length > MAX_RICH_BLOCKS || new Set(blockIds).size !== blockIds.length) return null
  return {
    ...(value as unknown as RichContentDocument),
    warnings: Array.isArray(value.warnings) ? value.warnings as string[] : [],
  }
}
