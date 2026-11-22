import { createHash } from 'node:crypto'
import { fishId, obj, officialRows, rowKey } from './memory.js'

const BASE = 'https://api.yuyuworld.app/v1/'
export const validKey = key => typeof key === 'string' && /^fwr_[^\s\x00-\x1f\x7f]{1,512}$/.test(key)
function retryMs(raw) {
  const duration = /^\d+$/.test(raw) ? Number(raw) * 1000 : Date.parse(raw) - Date.now()
  return Math.min(86_400_000, Math.max(0, duration || 0))
}
export class WatchError extends Error {
  constructor(status, retry) { super(`鱼世界观看接口 HTTP ${status}`); this.retry = retry }
}
export async function watchRequest(key, path, cursor = '', signal) {
  if (!validKey(key) || !['state', 'notify'].includes(path)) throw new Error('请先配置 fwr_ 观看密钥')
  const requestUrl = new URL(path, BASE)
  if (cursor) requestUrl.searchParams.set('cursor', cursor)
  const timeout = AbortSignal.timeout(18000)
  const response = await fetch(requestUrl, {
    method: 'GET', redirect: 'manual', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    headers: { Authorization: 'Bearer ' + key, Accept: 'application/json' },
  })
  if (response.status !== 200) {
    await response.body?.cancel().catch(() => {})
    throw new WatchError(response.status, retryMs(response.headers.get('Retry-After') ?? ''))
  }
  const chunks = []
  let total = 0
  for await (const chunk of response.body ?? []) {
    total += chunk.byteLength
    if (total > 512000) throw new Error('观看响应过大')
    chunks.push(chunk)
  }
  const result = JSON.parse(Buffer.concat(chunks).toString('utf-8'))
  if (!obj(result)) throw new Error('观看响应格式无效')
  return result
}
export async function sync(memory, key, get, signal) {
  const state = await get('state')
  if (fishId(state.fish) !== memory.fish) throw new Error('观看密钥与当前绑定的鱼不一致')
  if (state.stage !== 'live') return '鱼尚未入住；未读取通知'
  const [, previous] = memory.load()
  const fingerprint = createHash('sha256').update(key).digest('hex')
  const cursor = previous.key === fingerprint ? previous.cursor ?? '' : ''
  if (typeof cursor !== 'string' || cursor.length > 256) throw new Error('以前的通知游标无效')
  const notify = await get('notify', cursor)
  if (signal?.aborted) return '同步已停止'
  if (typeof notify.cursor !== 'string' || !notify.cursor.length || notify.cursor.length > 256 ||
      !Array.isArray(notify.items) || notify.items.length > 50) throw new Error('通知响应格式无效，已保留旧游标')
  const batch = officialRows(state, cursor ? notify : { items: [] })
  const starting = batch.find(row => row.kind === 'start')
  const signature = starting ? rowKey(starting) : ''
  const ignoreStart = signature && signature === previous.ignoreStart ? signature : ''
  if (ignoreStart) batch.splice(batch.indexOf(starting), 1)
  const count = memory.merge(batch, { key: fingerprint, cursor: notify.cursor, lastStart: signature, ignoreStart })
  const gap = cursor && Number.isSafeInteger(notify.skipped) && notify.skipped > 0 ? `；服务端略过 ${notify.skipped} 条旧通知` : ''
  return `${cursor ? '' : '首次建立通知基准；'}本次新增 ${count} 条${gap}`
}
