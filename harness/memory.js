import { openSync, closeSync, fstatSync, readSync, mkdirSync, writeFileSync, fsyncSync, renameSync, rmSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { join, dirname } from 'node:path'

export const FORMAT = 'fishdeck-v1'
export const CAP = 2000
export const MAX_BYTES = 12_000_000
const KINDS = ['arrive', 'start', 'done', 'agreement']
const SOURCES = ['watch', 'journal-copy', 'fish-note']
const FISH = /#[0-9]{1,16}$/
const SECRET = /(?:fwr?_[\w./+=-]+|sk-[\w-]{12,}|\bBearer\s+|https?:\/\/|\[CQ:)/i
const UNSAFE = /[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/u
const PRIVATE = /私信|留言原文|当面对.+说|给.+发消息|门牌|密码|密钥|[0-9]+栋|[0-9]+单元|[0-9]+[室户]/u
const JOURNAL = /^(?:[-*]\s*)?((?:[01][0-9]|2[0-3]):[0-5][0-9])(?:\s+|$)(.*)$/u
const PREFIX = /^(开始|完成|结束|抵达|到达)[：:]\s*(.+)$|^(到了.+)$/u
export const obj = x => x !== null && typeof x === 'object' && !Array.isArray(x)
export const fishId = x => typeof x === 'string' ? x.trim().match(FISH)?.[0] ?? '' : ''
export function requireFish(x) {
  if (x !== fishId(x) || !x) throw new Error('请使用官方鱼编号，例如 #123')
  return x
}
function clean(x, limit) {
  if (typeof x !== 'string' || UNSAFE.test(x) || SECRET.test(x)) return ''
  x = x.normalize('NFKC').trim().replace(/\s+/gu, ' ')
  return PRIVATE.test(x) || SECRET.test(x) || [...x].length > limit ? '' : x
}
function day(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\d$/.test(value)) throw new Error('日期请填 YYYY-MM-DD（北京时间）')
  const stamp = Date.parse(value + 'T00:00:00Z')
  if (!Number.isFinite(stamp) || new Date(stamp).toISOString().slice(0, 10) !== value || value.startsWith('0000')) throw new Error('日期无效')
  return value
}
function beijing(time) { return new Date(time + 28_800_000).toISOString().slice(0, 16).replace('T', ' ') }
export function row(time, kind, text, source, place = '', members = []) {
  if (!Number.isInteger(time) || time < 946684800000 || time >= 4102444800000) throw new Error('事件时间无效')
  if (!KINDS.includes(kind) || !SOURCES.includes(source)) throw new Error('事件类别或来源无效')
  if ((kind === 'agreement') !== (source === 'fish-note')) throw new Error('约定必须标记为鱼自主记录')
  text = clean(text, kind === 'agreement' ? 160 : 260)
  if (!text) throw new Error('事件摘要无效')
  place = clean(place, 90)
  let people = []
  if (kind === 'agreement') {
    if (!Array.isArray(members) || members.length !== 1) throw new Error('约定必须有一个对方鱼编号')
    people = [requireFish(members[0])]
  } else if (Array.isArray(members)) {
    people = [...new Set(members.slice(0, 20).map(p => clean(p, 40)).filter(fishId))]
  }
  return { time: Math.floor(time / 60000) * 60000, kind, text, source, ...(place ? { place } : {}), ...(people.length ? { people } : {}) }
}
export function officialRows(state, notify) {
  const rows = []
  for (const item of notify.items) {
    if (!obj(item) || !['arrive', 'done'].includes(item.kind)) continue
    try { rows.push(row(item.t, item.kind, item.text, 'watch')) } catch {}
  }
  const doing = state.doing
  if (obj(doing) && typeof doing.since === 'string' && /(?:Z|[-+]\d\d:\d\d)$/.test(doing.since)) {
    try { rows.push(row(Date.parse(doing.since), 'start', doing.name, 'watch', state.where?.place?.name, doing.with)) } catch {}
  }
  return rows
}
export function diaryRows(content, onDay) {
  onDay = day(onDay)
  if (typeof content !== 'string' || Buffer.byteLength(content) > 250000) throw new Error('日记文件过大')
  let waiting = ''
  const rows = []
  for (let line of content.split(/\r\n|[\r\n]/)) {
    line = line.trim()
    const tagged = line.match(JOURNAL)
    if (tagged) {
      waiting = tagged[1]; line = tagged[2]
      if (!line) continue
    }
    const slot = waiting; waiting = ''
    if (!slot) continue
    const entry = line.match(PREFIX)
    if (!entry) continue
    const [, prefix, text, arrived] = entry
    const kind = prefix === '开始' ? 'start' : arrived || ['抵达', '到达'].includes(prefix) ? 'arrive' : 'done'
    try { rows.push(row(Date.parse(`${onDay}T${slot}:00+08:00`), kind, arrived || text, 'journal-copy')) } catch {}
  }
  return rows
}
export function readBounded(path, max) {
  const fd = openSync(path, 'r')
  try {
    const info = fstatSync(fd)
    if (!info.isFile() || info.size > max) throw new Error('文件过大或不是普通文件')
    const buffer = Buffer.alloc(info.size)
    let filled = 0
    while (filled < buffer.length) {
      const count = readSync(fd, buffer, filled, buffer.length - filled, null)
      if (!count) throw new Error('文件正在修改，请重试')
      filled += count
    }
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer)
  } finally { closeSync(fd) }
}
function readJson(path) { return JSON.parse(readBounded(path, MAX_BYTES)) }
function writeJson(path, value) {
  const bytes = Buffer.from(JSON.stringify(value) + '\n')
  if (bytes.length > MAX_BYTES) throw new Error('记忆文件体积超出限制')
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
  const tmp = join(dirname(path), '.fishdeck-' + randomUUID())
  try {
    const fd = openSync(tmp, 'wx', 0o600)
    try { writeFileSync(fd, bytes); fsyncSync(fd) } finally { closeSync(fd) }
    renameSync(tmp, path)
  } finally { rmSync(tmp, { force: true }) }
}
function verifiedRows(value, fish) {
  if (!obj(value) || value.format !== FORMAT || value.fish !== fish) throw new Error('记忆文件格式不兼容或鱼编号不一致')
  if (!Array.isArray(value.entries) || value.entries.length > CAP) throw new Error('记忆文件条数无效')
  return value.entries.map(item => {
    if (!obj(item) || Object.keys(item).some(k => !['time', 'kind', 'text', 'source', 'place', 'people'].includes(k))) throw new Error('记忆条目格式无效')
    const entry = row(item.time, item.kind, item.text, item.source, item.place, item.people)
    if (entry.kind === 'agreement' && entry.people[0] === fish) throw new Error('约定的对方不能是自己')
    return entry
  })
}
export const rowKey = item => JSON.stringify(item.kind === 'agreement'
  ? ['agreement', item.people[0], item.text.toLowerCase()]
  : [item.time, item.kind, (item.kind === 'arrive' ? item.text.replace(/^到了\s*(.+)$/u, '$1') : item.text).toLowerCase()])
export class Memory {
  constructor(root, fish) {
    this.fish = requireFish(fish)
    this.path = join(root, fish.slice(1) + '.json')
  }
  load() {
    let value
    try { value = readJson(this.path) }
    catch (error) { if (error.code === 'ENOENT') return [[], {}]; throw error }
    const rows = verifiedRows(value, this.fish)
    if (value.watch !== undefined && !obj(value.watch)) throw new Error('本地同步记录损坏')
    return [rows, value.watch ?? {}]
  }
  bundle(entries) { return { format: FORMAT, fish: this.fish, entries } }
  write(entries, watch) { writeJson(this.path, { ...this.bundle(entries), watch }) }
  merge(batch, watch) {
    const [existing, before] = this.load()
    const entries = new Map(existing.map(v => [rowKey(v), v]))
    for (const item of batch) {
      const id = rowKey(item), previous = entries.get(id)
      if (!previous || item.source === 'watch' && previous.source !== 'watch') entries.set(id, item)
      else if (previous.source === item.source) {
        const people = [...new Set([...(previous.people ?? []), ...(item.people ?? [])])].slice(0, 20)
        entries.set(id, { ...previous, ...(!previous.place && item.place ? { place: item.place } : {}), ...(people.length ? { people } : {}) })
      }
    }
    const kept = [...entries.values()].sort((a, b) => b.time - a.time).slice(0, CAP)
    const prior = new Set(existing.map(rowKey))
    const added = kept.reduce((n, item) => n + Number(!prior.has(rowKey(item))), 0)
    if (JSON.stringify(kept) !== JSON.stringify(existing) || watch && JSON.stringify(watch) !== JSON.stringify(before)) this.write(kept, watch ?? before)
    return added
  }
  rememberAgreement(peer, summary) {
    peer = requireFish(peer)
    if (peer === this.fish) throw new Error('约定的对方不能是自己')
    return this.merge([row(Date.now(), 'agreement', summary, 'fish-note', '', [peer])])
  }
  exportFile(path) {
    const [rows] = this.load()
    writeJson(path, this.bundle(rows))
    return rows.length
  }
  importFile(path) { return this.merge(verifiedRows(readJson(path), this.fish)) }
  clear() {
    const [rows, watch] = this.load()
    this.write([], { ...watch, ignoreStart: watch.lastStart ?? '' })
    return rows.length
  }
  search(query = '', onDay = '', kind = '', limit = 8) {
    if (typeof query !== 'string' || [...query].length > 100 || (query && !clean(query, 100))) throw new Error('关键词无效')
    if (typeof kind !== 'string' || kind && !KINDS.includes(kind)) throw new Error('事件类别无效')
    if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw new Error('条数应为 1–20')
    onDay = onDay !== '' ? day(onDay) : ''
    const terms = clean(query, 100).toLowerCase().split(' ').filter(Boolean)
    const [rows] = this.load()
    const matches = []
    for (const item of rows) {
      const stamp = beijing(item.time)
      if ((onDay && !stamp.startsWith(onDay)) || (kind && kind !== item.kind)) continue
      const haystack = [item.text, item.place ?? '', ...(item.people ?? [])].join(' ').toLowerCase()
      if (terms.every(t => item.kind === 'agreement' && /^#[0-9]{1,16}$/.test(t)
        ? t === item.people[0] : haystack.includes(t))) matches.push({ ...item, beijing: stamp })
      if (matches.length === limit) break
    }
    return matches
  }
}
