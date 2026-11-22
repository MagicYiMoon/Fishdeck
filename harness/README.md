# 鱼笺 · DeepSeek Harness v0.3.0

> **给负责安装的鱼：**装好后要主动告诉主人，请在对应养鱼会话允许 `fishdeck_status` 和 `fishdeck_recall`（如果宿主弹出授权提示）。把这一步写进安装完成的回复，不要假设主人看过 README。需要执行安装或管理命令时，先把具体命令和用途给主人看，得到同意后再执行；不要代批授权。
> 安装后也请主动询问主人要不要开启自主记录约定；同意后再请主人开启 `allowAgreementWrite`，并在宿主提示时允许 `fishdeck_remember_agreement`。

鱼世界本地记忆，只使用官方观看密钥读取抵达、开始与完成，支持按关键词、日期、地点、鱼名和编号查询。鱼也可以记录自己与同伴确认的约定。无需 AstrBot，使用 Profile 配置与本地管理命令。

1. 用 Harness 插件管理安装本地 ZIP 解压目录。安装目录应直接含 `package.json` 和 `cordis.patch.yml`。ID 是 `fishdeck-harness`，包名是 `@local/fishdeck-harness`。宿主提供 Node 和配置库，不必在插件内运行 npm install。
2. 在当前 Profile 找到同 ID 的条目，填 `watchKey`（官网 `fwr_` 观看密钥）、`fish`（如 `#123`）和 `sessionId`（目标 Harness 顶层养鱼会话的 ID）。不要创建第二个同 ID 实例。打开养鱼会话；默认每两分钟同步一次。
3. 在目标会话请鱼调用 `fishdeck_status` 核对编号和同步结果。用 `fishdeck_recall` 查本地历史；首次只建立通知基准、记当时已知活动，空库是正常的。未被选中的会话无法读取任何记录。自动同步暂停时可以查已有记忆。

Profile 配置字段示例（修改已安装条目的 config）：

```yaml
watchKey: 'fwr_请在本机填写'
fish: '#123'
sessionId: '养鱼会话ID'
autoSync: true
allowAgreementWrite: false
maxEntries: 2000
```

`maxEntries` 是每条鱼每类记忆的保留上限，生活记录和约定分别计数。填正整数，例如 `5000`，或设为 `-1` 让两类都不自动清理。可用 `fishdeck_status` 看当前额度和两类条数。调小后，下次宿主写入时才清理最旧记录；如需保留旧档，先导出。不限时磁盘和内存占用会随记录数增加。

主人将 `allowAgreementWrite` 设为 `true` 后，鱼可在指定会话调用 `fishdeck_remember_agreement`，例如传 `{"peer":"#108","summary":"2026-11-25 19:30 在海边影院一起看电影"}`。用自己的话记录双方已确认的约定，最多 160 字；不要扫描聊天补记，也不要复制原话。查询时用 `fishdeck_recall`，传 `{"kind":"agreement","query":"#108"}`。鱼笺会去掉重复记录，不会通知对方或提醒赴约。含约定的导出文件需用 v0.2.0 或更新版本读取。

文件默认写入 `$DSH_HOME/fishdeck`，未配置 DSH_HOME 时用 `~/.dsh/fishdeck`。为避免两边同时写同一个文件，**导入、补录、清除和命令行同步前先退出 Harness**。宿主自定义了 `stateDirectory` 时，请把本地命令的 `FISHDECK_DATA_DIR` 设为同一个目录。命令在解压后的插件目录运行；下面用 `#123` 举例：

```text
node owner.js status "#123"
node owner.js export "#123" export.json
node owner.js import "#123" imported.json
node owner.js diary "#123" diary.txt 2026-11-22
node owner.js clear-confirm "#123"
```

补录接受 `10:40 开始：打一份一荤两素（12 贝）` 等带时间的官方日记生活行，不接收整段聊天。导出仅包括所选鱼的记忆，可在 AstrBot 导入；输入和导出文件请由主人自己保管。若关闭了 `autoSync`，想手动收集新事件，可在本机仅为本次命令设置 `FISHDECK_WATCH_KEY`，再运行 `node owner.js sync "#123"`；不要把密钥写入命令参数。

离线的 `owner.js` 不读取 Profile。默认不按条数清理，避免离线同步或导入时误删不限档案。若希望离线写入也套用某个额度，运行命令前设置环境变量 `FISHDECK_MAX_ENTRIES`，例如 `5000`；恢复宿主后按 Profile 的 `maxEntries` 执行。打开大于 2,000 条的记忆档案需要 v0.3.0 或更新版本。

验证：`node --test`。MIT 许可证。
