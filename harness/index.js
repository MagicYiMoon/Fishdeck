import Schema from '@deepseek-ai/schemastery'
import { start } from './runtime.js'

export const name = 'fishdeck-harness'
export const inject = ['agents', 'tools']
export const Config = Schema.object({
  watchKey: Schema.string().default('').description('fwr_ 开头的官方观看密钥，通过当前 Profile 填写。'),
  fish: Schema.string().default('').description('此观看密钥对应的鱼编号，例如 #123。'),
  sessionId: Schema.string().default('').description('仅此养鱼会话可使用记忆工具。填 Harness 会话 ID，不是鱼编号。'),
  stateDirectory: Schema.string().default('').description('留空使用 DSH_HOME 下的 fishdeck 目录。'),
  autoSync: Schema.boolean().default(true).description('已配置后每两分钟读观看接口，不调用 MCP。'),
  allowAgreementWrite: Schema.boolean().default(false).description('仅在主人同意后开启，允许鱼记录双方已确认的约定。'),
})
export function apply(ctx, config) { start(ctx, config) }
