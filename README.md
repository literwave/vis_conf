# 星图 · 游戏配置导表工具

用 TSV 管理游戏配置表，支持 Windows 桌面和 Android。

- 分页查看和编辑表格，可添加、删除、拖动和复制数据行。
- 管理列、配置导出规则，并分别生成前后端文件。
- 用小缩略图预览配置表中的本地图片路径。
- 桌面端可使用 AI Agent 生成配置修改预览，并确认后应用。

## 快速开始

```powershell
python -m pip install -r requirements-desktop.txt
python app.py
```

首次启动需要联网准备 Flet 桌面运行时。Windows 遇到缓存目录重命名权限错误时，程序会短暂重试；如果其他启动进程已准备好缓存，则复用该缓存。

## Windows 分发

构建需要 Windows x64、Python、Flet CLI 和 Inno Setup 6：

```powershell
python -m pip install "flet[cli]>=1.0.0,<2.0.0"
.\build_installer.ps1
```

构建脚本会生成两种分发包：

| 类型 | 产物 | 使用方式 |
|---|---|---|
| 安装版 | `dist/installer/StarMap-Setup-1.0.0.exe` | 安装后从开始菜单启动 |
| 便携版 | `dist/portable/StarMap-Portable-1.0.0.zip` | 解压后运行 `star_map/star_map.exe` |

安装版默认安装到 `%LOCALAPPDATA%\Programs\GameConfigAssistant`。可通过 `.\build_installer.ps1 -Version 1.1.0` 指定版本。

> **签名与安全提示**
>
> 当前安装器和程序未进行代码签名。启用了 Windows 智能应用控制或企业应用控制策略的设备可能会拦截程序。改名、管理员运行或改用 ZIP 都不能单独解除拦截。

### 智能应用控制拦截时

如果你信任该程序，并且只在自己的设备上使用，可按以下步骤继续。关闭智能应用控制会降低设备防护能力，而且设置可能持续生效；公司管理设备请联系管理员。

1. 打开“Windows 安全中心”。
2. 进入“应用和浏览器控制” → “智能应用控制设置”，选择“关闭”。
3. 使用安装版，运行 `dist/installer/StarMap-Setup-1.0.0.exe`；或解压便携版，运行 `star_map/star_map.exe`。
4. 安装版从开始菜单启动“星图 游戏配置导表工具”；便携版直接运行解压后的程序。

Windows 当前不提供只允许单个程序通过智能应用控制的选项。如果设置不可更改，请联系设备管理员，不要尝试绕过组织策略。疑似误报时，可通过 [Microsoft 安全情报文件分析](https://www.microsoft.com/wdsi/filesubmission)提交文件评估；提交不保证解除拦截。

## Android

在 Windows 上构建 APK（首次构建需要联网；Flet CLI 会准备所需工具链）：

```powershell
python -m pip install "flet[cli]>=1.0.0,<2.0.0"
flet build apk --module-name app --project game-config-assistant --org com.literwave --product "星图"
```

产物位于 `build/apk/`。在应用的“导出设置”中选择手机上的 TSV；导出时通过系统保存对话框生成 ZIP，包含 `backend/` 和 `frontend/` 文件夹。手机上的编辑仅保留在当前会话，不会覆盖原文件。

## 示例：使用 test 配置表

仓库的 `test/` 目录包含道具、角色、技能、怪物和等级奖励配置表。

![导出设置界面示例](assets/export-settings-example.png)

1. 点击“导出设置”，在“配置文件目录”选择 `test/`。
2. 从左侧配置表列表打开 `test_config.tsv`。它包含 `id`、`name` 和 `icon_path` 三列；图标列会显示小缩略图，点击后可编辑原始路径。
3. 点击“导表规则”设置 key，点击“管理列”添加或调整字段。
4. 选择后端/前端格式和导出目录，再点击“全量导出”或“增量导出”。

`test/test_config.tsv` 的图片路径为 `../assets/assistant-icon.png`，以 TSV 文件所在目录为基准。`export/client/` 和 `export/server/` 是前后端导出目录示例。

## 常用操作

| 操作 | 说明 |
|---|---|
| 搜索配置表 | 文件名模糊筛选，不区分大小写；例如 `skcf` 可匹配 `skill_config.tsv` |
| 新建/删除配置表 | 列表标题旁的 `+` 新建；删除前会确认。桌面端操作所选目录中的文件 |
| 编辑单元格 | 点击单元格；编辑窗口右上角 `×` 可关闭，未保存的修改会丢弃 |
| 管理列 | 添加列时可设置名称、类型、导出端、注释和默认值；删除列会移除该列数据并请求确认 |
| 移动行 | 拖动行首手柄调整顺序 |
| 复制并插入行 | 选中源行后按 `Ctrl+C`，再选目标行并按 `Ctrl+V`；副本插入目标行之前，不覆盖数据 |
| 撤销 | 按 `Ctrl+Z` 撤销最近一次编辑、行排序、复制、新增或删除，最多保留 50 步 |
| 分页 | 可选择每页显示 10、20、50 或 100 行；新增行会追加到表格末尾并跳转到所在页 |
| AI Agent（桌面端） | 顶部「AI Agent」可连接 Cursor Agent CLI 或 OpenAI 兼容 API；仅提供当前页，确认预览后应用，可用 `Ctrl+Z` 撤销 |

复制粘贴快捷键使用应用内行剪贴板，不会替代系统文本剪贴板。编辑和增量导出队列仅保留在当前会话，不会写回原 TSV；切换配置表不会丢失当前会话中的编辑。

### AI Agent（桌面端）

点击窗口顶部的「AI Agent」，再点右上角齿轮配置连接方式和模式：

- **Cursor Agent CLI**：按下面的 Windows 安装步骤安装并登录 Cursor CLI。可选 Ask（只读问答）或 Agent（可调用工具）；CLI 在临时目录中启动，当前表当前页的数据作为提示提供。
- **OpenAI 兼容 API**：填写 HTTPS API 基础地址、模型名和 API Key。API Key 存在系统凭据库中，不会写入 `settings.json`；请求会发送到配置的服务地址。

Agent 只建议修改当前页已有行和列。修改先显示类型校验后的预览；只有点击「确认应用」才会改动当前会话，可用 `Ctrl+Z` 撤销。它不会自动写入 TSV；导出仍由用户操作。Android 暂不提供 Agent 功能。

> Cursor CLI 的 Agent 模式可运行终端命令并读写本机文件；临时工作目录不是安全沙箱。仅在信任请求内容时使用。预览确认只控制本工具对表格的应用，不限制 CLI 的本机工具权限。

#### Windows 安装 Cursor Agent CLI

1. 打开 **PowerShell**，运行 Cursor 官方安装命令：

   ```powershell
   irm 'https://cursor.com/install?win32=true' | iex
   ```

   如果你不希望执行 PowerShell 安装脚本，可从 [Cursor CLI 官方文档](https://cursor.com/docs/cli)查看最新安装方式。

2. 安装完成后，**关闭并重新打开 PowerShell**，运行以下命令确认 CLI 已加入 PATH：

   ```powershell
   agent --version
   ```

3. 运行 `agent`，按 CLI 提示在浏览器中登录 Cursor 账号并完成授权。登录成功后可退出 CLI。
4. 如果星图在安装 CLI 时已经打开，请完全退出并重新启动星图，让它读取更新后的 PATH。
5. 在星图顶部打开「AI Agent」，点击右上角齿轮，选择「Cursor Agent CLI」及 Ask 或 Agent 模式，保存连接，再发送请求。

如果提示找不到 Cursor Agent CLI，先在**重新打开的 PowerShell**里再次运行 `agent --version`。若 PowerShell 也找不到命令，请根据官方文档检查安装是否完成及 CLI 所在目录是否已加入用户 PATH，然后重新启动星图。

## TSV 格式与导出

每个 TSV 使用 UTF-8 编码，前四行为表格元数据：

| 行 | 内容 |
|---|---|
| 第 1 行 | 字段名 |
| 第 2 行 | 数据类型 |
| 第 3 行 | 导出端 |
| 第 4 行 | 字段注释 |
| 第 5 行起 | 数据 |

支持字符串、整数、小数、布尔值、JSON、Lua 表数组和 Lua 表字典。导出端可设为后端、前端或两端；默认后端 Lua、前端 JSON。

空单元格以及嵌套数据中的 `null`/`nil` 会在导出时省略；数组中的空值也会移除，因此后续元素会前移。Key 为空仍会报错。

“全量导出”处理配置目录中的全部 TSV；“增量导出”只列出本次会话修改过的表，默认全选。未选中的表保留在队列中，导出成功的表才会移出队列。

导表规则默认使用 `id`（存在时）。多个 key 按列顺序嵌套，例如 `[key1][key2]`；不选择 key 时导出记录数组。Key 为空、重复或未勾选对应导出端时会报错。前后端若生成相同路径，工具会停止导出并提示冲突。

设置的目录、文件格式和各表 key 规则会自动保存：

```text
%APPDATA%\GameConfigAssistant\settings.json
```

更多输入语法和导出细节：

<details>
<summary>展开查看 Lua 表、图片预览和导出文件说明</summary>

- Lua 数组示例：`{1, 2, "three"}`。
- Lua 字典示例：`{id = 1, name = "道具"}` 或 `{["id"] = 1}`。支持嵌套表及 `true`、`false`、`nil`；不会执行 Lua 代码。
- JSON 导出时 Lua 表会转换为数组或对象。Lua 导出采用多行缩进格式；TSV 单元格内的 Lua 表值保持单行。
- 字符串字段填写本地 PNG、JPG、JPEG、GIF、WEBP 或 BMP 路径时显示缩略图。相对路径以 TSV 所在目录为基准；点击缩略图可查看或编辑路径。
- 导出文件名使用 `<配置表名>.lua` 或 `<配置表名>.json`，前后端通过各自目录区分。未启用对应导出端的列不会写入该端文件。
- Lua 文件头会标注作者 `liter_wave`、生成工具及来源 TSV 文件名。
- 导出完成后会显示处理表数量、生成文件数量和每张表的输出路径。

</details>
