import { join } from 'node:path'
import { Memory, diaryRows, readBounded } from './memory.js'
import { defaultDirectory } from './runtime.js'
import { sync, watchRequest, validKey, WatchError } from './watch.js'

// This program runs locally for the owner, never as a model tool or web endpoint.
const [action, fish, file, date] = process.argv.slice(2)
const usage = '用法：node owner.js status|export|import|diary|clear-confirm|sync "#鱼编号" [文件] [北京时间 YYYY-MM-DD]'
try {
  if (!['status', 'export', 'import', 'diary', 'clear-confirm', 'sync'].includes(action) || !fish) throw new Error(usage)
  const root = process.env.FISHDECK_DATA_DIR?.trim() || defaultDirectory()
  const memory = new Memory(join(root, 'records'), fish)
  if (action === 'status') console.log(`${fish}：${memory.load()[0].length} 条`)
  else if (action === 'export' && file) console.log(`已导出 ${memory.exportFile(file)} 条`)
  else if (action === 'import' && file) console.log(`新增 ${memory.importFile(file)} 条`)
  else if (action === 'diary' && file && date) {
    const rows = diaryRows(readBounded(file, 250000), date)
    console.log(`识别 ${rows.length} 条生活事件，新增 ${memory.merge(rows)} 条`)
  } else if (action === 'clear-confirm') console.log(`已清除 ${memory.clear()} 条`)
  else if (action === 'sync') {
    const key = process.env.FISHDECK_WATCH_KEY?.trim()
    if (!validKey(key)) throw new Error('请在本机环境变量 FISHDECK_WATCH_KEY 配置 fwr_ 观看密钥')
    console.log(await sync(memory, key, (p, c) => watchRequest(key, p, c)))
  } else throw new Error(usage)
} catch (error) {
  console.error(error instanceof WatchError ? error.message : '操作未完成，请检查命令、鱼编号、文件或观看配置。\n' + usage)
  process.exitCode = 1
}
