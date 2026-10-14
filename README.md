# 星图 · 游戏配置导表工具

用 TSV 管理游戏配置表，支持 Windows 桌面和 Android。

- 分页查看和编辑表格，可添加、删除、拖动和复制数据行。
- 管理列、配置导出规则，并分别生成前后端文件。
- 用小缩略图预览配置表中的本地图片路径。

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

复制粘贴快捷键使用应用内行剪贴板，不会替代系统文本剪贴板。编辑和增量导出队列仅保留在当前会话，不会写回原 TSV；切换配置表不会丢失当前会话中的编辑。

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
