import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { Memory, RetentionError, diaryRows, row } from '../memory.js'
import { sync } from '../watch.js'
import { start } from '../runtime.js'

const T = Date.parse('2026-11-23T00:05:00+08:00')
function root(t) {
  const path = mkdtempSync(join(tmpdir(), 'fishdeck-'))
  t.after(() => rmSync(path, { recursive: true, force: true }))
  return path
}
test('capture only by allowlist, keeps cursor after failure and never touches another fish', async t => {
  const path = root(t), memory = new Memory(path, '#123')
  const state = { fish: '鱼#123', stage: 'live', doing: { name: '看电影', since: new Date(T).toISOString(), with: ['阿紫#108'] },
    where: { place: { name: '海边影院' } } }
  const visit = { kind: 'arrive', t: T, text: '到了北坡菜园' }
  const done = { kind: 'done', t: T, text: '浇完水' }
  const notify = { cursor: 'first', items: [visit] }
  const calls = []
  const get = async (path, cursor = '') => { calls.push([path, cursor]); return path === 'state' ? state : notify }
  assert.match(await sync(memory, 'fwr_fake', get), /首次/)
  assert.equal(memory.search('影院 #108', '2026-11-23')[0].text, '看电影')
  assert.equal(memory.search('菜园').length, 0)
  Object.assign(notify, { cursor: 'next', items: [visit, done, { kind: 'message', t: T, text: 'private' }, { ...done, text: 'fwr_should_not_save' }] })
  assert.match(await sync(memory, 'fwr_fake', get), /新增 2/)
  assert.deepEqual(calls.at(-1), ['notify', 'first'])
  assert.match(await sync(memory, 'fwr_fake', get), /新增 0/)
  notify.cursor = ''
  await assert.rejects(sync(memory, 'fwr_fake', get))
  assert.equal(memory.load()[1].cursor, 'next')
  state.fish = '别的鱼#999'
  await assert.rejects(sync(memory, 'fwr_fake', get))
  assert.deepEqual(calls.at(-1), ['state', ''])
  assert.deepEqual(new Memory(path, '#999').search(), [])
  state.fish = '鱼#123'
  Object.assign(notify, { cursor: 'last', items: [] })
  assert.equal(memory.clear(), 3)
  await sync(memory, 'fwr_fake', get)
  assert.equal(memory.search().length, 0)
})
test('host isolates memory and requires owner opt-in for writing agreements', async t => {
  const stateDirectory = root(t), destination = { id: 'main' }, other = { id: 'other' }
  const registered = new Map(), disposers = []
  const ctx = { agents: { roots: () => [destination, other] },
    effect(f) { disposers.push(f()) },
    tools: { register(tool) { registered.set(tool.name, tool); return () => registered.delete(tool.name) } } }
  t.after(() => disposers.reverse().forEach(d => d()))
  const fixture = new Memory(join(stateDirectory, 'records'), '#123')
  fixture.merge(diaryRows('00:05 开始：看电影\n00:06 私信：不可见', '2026-11-23'))
  const config = { fish: '#123', sessionId: 'main', autoSync: false, stateDirectory, maxEntries: -1 }
  const host = start(ctx, config, () => assert.fail('unexpected network request'))
  await host.tick()
  const tool = registered.get('fishdeck_recall')
  assert.equal(tool.execute({}, { agent: other }).available, false)
  assert.equal(tool.execute({}, { agent: { id: 'main' } }).available, false)
  assert.equal(tool.execute({ query: '电影' }, { agent: destination }).records[0].text, '看电影')
  const file = join(stateDirectory, 'portable.json')
  assert.equal(fixture.exportFile(file), 1)
  const portable = JSON.parse(readFileSync(file, 'utf8'))
  assert.deepEqual(Object.keys(portable), ['format', 'fish', 'entries'])
  assert.throws(() => new Memory(stateDirectory, '#999').importFile(file))

  const write = registered.get('fishdeck_remember_agreement')
  const args = { peer: '#108', summary: '2026-11-25 19:30 在海边影院一起看电影' }
  assert.equal(write.execute(args, { agent: destination }).available, false)
  assert.equal(tool.execute({ kind: 'agreement' }, { agent: destination }).records.length, 0)
  config.allowAgreementWrite = true
  assert.equal(write.execute(args, { agent: other }).available, false)
  assert.equal(write.execute(args, { agent: { id: 'main' } }).available, false)
  assert.equal(write.execute({ ...args, peer: '#123' }, { agent: destination }).available, false)
  assert.equal(write.execute({ ...args, summary: 'fwr_sensitive' }, { agent: destination }).available, false)
  assert.equal(write.execute(args, { agent: destination }).added, true)
  assert.equal(write.execute(args, { agent: destination }).added, false)
  assert.deepEqual(tool.execute({ query: '#108', kind: 'agreement' }, { agent: destination }).records[0].people, ['#108'])
  config.allowAgreementWrite = false
  assert.equal(write.execute(args, { agent: destination }).available, false)
  assert.equal(tool.execute({ kind: 'agreement' }, { agent: destination }).records.length, 1)
  const status = registered.get('fishdeck_status').execute({}, { agent: destination })
  assert.equal(status.maxEntries, -1)
  assert.equal(status.lifeCount, 1)
  assert.equal(status.agreementCount, 1)
})

test('custom quotas isolate agreements and trim only on write', t => {
  const path = root(t)
  for (const invalid of [0, -2, '100', 2.5, true, null]) {
    assert.throws(() => new Memory(path, '#123', invalid), RetentionError)
  }
  assert.equal(new Memory(path, '#123').maxEntries, 2000)
  const capped = new Memory(path, '#123', 1)
  capped.merge([row(T, 'done', '浇菜', 'watch')], { cursor: 'known' })
  capped.merge([
    row(T + 60_000, 'done', '吃饭', 'watch'),
    row(T + 60_000, 'agreement', '一起看电影', 'fish-note', '', ['#108']),
  ])
  assert.deepEqual(capped.search().map(item => item.text), ['吃饭', '一起看电影'])
  assert.equal(capped.merge([row(T + 60_000, 'agreement', '一起种菜', 'fish-note', '', ['#108'])]), 1)
  assert.equal(capped.search('', '', 'agreement')[0].text, '一起种菜')
  new Memory(path, '#123', -1).merge([row(T + 120_000, 'done', '散步', 'watch')])
  assert.equal(capped.load()[0].length, 3)
  capped.merge([])
  assert.deepEqual(capped.search().map(item => item.text), ['散步', '一起种菜'])
  assert.equal(capped.load()[1].cursor, 'known')
})
