# 星图 · 游戏配置导表工具

基于 Flet 的游戏配置表工具，使用 TSV（制表符分隔的纯文本）配置格式。提供行列统计、自定义列及注释、分页预览、单元格点击编辑，以及分别导出后端和前端配置；支持 Windows 桌面及 Android 手机。

首次运行需要准备 Flet 桌面运行时；首次安装依赖和运行时需要联网。Windows 启动时会对 Flet 运行时缓存目录重命名遇到的 `PermissionError` 进行短暂重试；如果另一个启动进程已生成完整缓存，则复用该缓存。桌面模式提供系统文件夹选择器，导出文件会写入选择的本机目录。Android 使用系统文件选择器，不需要用户手动配置存储权限。

## 运行

```powershell
python -m pip install -r requirements-desktop.txt
python app.py
```

### Windows 安装包

安装包使用 Flet/PyInstaller 构建应用目录，再由 Inno Setup 生成可安装、可卸载的安装程序。需要 Windows x64、Python 环境及 Inno Setup 6。当前生成的安装包和程序尚未进行代码签名；启用了 Smart App Control 或企业代码完整性策略的 Windows 设备可能会拦截程序。对外发布时建议使用受信任的代码签名证书签名后再分发。

```powershell
python -m pip install "flet[cli]>=1.0.0,<2.0.0"
.\build_installer.ps1
```

运行构建脚本会同时生成安装程序 `dist/installer/StarMap-Setup-1.0.0.exe` 和便携版压缩包 `dist/portable/StarMap-Portable-1.0.0.zip`。安装版默认安装至 `%LOCALAPPDATA%\Programs\GameConfigAssistant`，主程序名为 `star_map.exe`；便携版解压后运行 `star_map/star_map.exe`，示例表位于同目录的 `examples/test/`。可通过参数指定版本，例如 `.\build_installer.ps1 -Version 1.1.0`。便携压缩包不会绕过 Windows 对未签名程序的应用控制拦截。

#### Windows 提示“智能应用控制已阻止可能不安全的应用”时

这是 Windows 无法验证未签名程序的发布者时可能出现的安全拦截。安装器和安装后的 `star_map.exe` 是不同程序：安装器能够打开或完成安装，不代表 Windows 会允许主程序启动。改文件名、以管理员身份运行或改用 ZIP 都不能单独解除智能应用控制；Windows 当前也不提供针对单个应用的“允许运行”按钮。

- **仅在自己的设备使用（会降低防护能力）：**
  1. 打开“开始”菜单，搜索并打开“Windows 安全中心”。
  2. 进入“应用和浏览器控制” → “智能应用控制设置”，选择“关闭”。如果该选项不可用，设备可能受组织策略管理，请联系管理员，不要尝试绕过策略。
  3. 再运行 `dist/installer/StarMap-Setup-1.0.0.exe` 安装；或先解压 `dist/portable/StarMap-Portable-1.0.0.zip`，再运行 `star_map/star_map.exe`。
  4. 安装版可从开始菜单启动“星图 游戏配置导表工具”；便携版直接运行解压目录中的程序。

  关闭智能应用控制会降低设备的防护能力，而且设置可能持续生效；仅在自己信任该程序并理解风险时才这样做。不要为了运行来历不明的程序关闭此保护。
- **怀疑是误报：**可通过 [Microsoft 安全情报文件分析](https://www.microsoft.com/wdsi/filesubmission)提交文件供评估；提交不保证会解除拦截。
- **面向公众分发：**优先考虑通过 Microsoft Store 发布，或使用受信任的代码签名证书签署程序和安装器。ZIP 只是打包形式，不会改变程序的签名状态。

更多信息请参阅 [Microsoft 智能应用控制常见问题](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)。

### Android 手机

Windows 上可以构建 Android APK。首次构建需要联网；Flet CLI 会检查并准备 Flutter SDK、Android SDK 和 JDK（也可使用已安装的 Android Studio 工具链）。

```powershell
python -m pip install "flet[cli]>=1.0.0,<2.0.0"
flet build apk --module-name app --project game-config-assistant --org com.literwave --product "星图"
```

构建产物位于 `build/apk/`。安装后，在“导出设置”中从手机文件选择器多选 TSV 配置表；搜索并打开配置表后可照常编辑。手机导出会通过系统保存对话框生成 ZIP，包内用 `backend/` 和 `frontend/` 区分两端文件。为避免覆盖源文件，手机模式不直接写入任意导出目录；导入文件和未导出的修改仅在当前应用会话保留。

## 示例与导出目录

- `test/` 中包含可直接打开的 TSV 示例：道具、角色、技能、怪物和等级奖励配置，覆盖字符串、整数、小数、布尔值、JSON、Lua 表数组及 Lua 表字典。
- `export/client/` 与 `export/server/` 分别作为前端、后端导出目录示例；可在“导出设置”中选择对应文件夹。

### 使用示例

![导出设置界面示例](assets/export-settings-example.png)

1. 点击右上角“导出设置”，在“配置文件目录”选择 `test/` 文件夹。桌面端会列出该目录下的 TSV；示例中包含 `game_config.tsv`、`character_config.tsv`、`skill_config.tsv`、`monster_config.tsv`、`level_reward.tsv` 和 `test_config.tsv`。
2. 从左侧“TSV 配置表”列表点击 `test_config.tsv`。该示例有 `id`、`name` 和 `icon_path` 三列；`icon_path` 使用相对路径 `../assets/assistant-icon.png`，表格中会显示小图标而不是路径。点击图标单元格可打开编辑框查看或修改路径。
3. 其他示例也可直接打开查看：`game_config.tsv` 展示 Lua 数组与 Lua 字典；`character_config.tsv`、`skill_config.tsv`、`monster_config.tsv` 和 `level_reward.tsv` 展示不同业务字段和类型。
4. 点击“导表规则”检查当前表的 key 字段，点击“管理列”调整字段；修改单元格后，当前会话中的表会加入增量导出列表。
5. 点击“全量导出”处理目录中的全部 TSV，或点击“增量导出”选择本次修改过的表。设置后端/前端格式和导出目录后，导出结果会分别写到相应目录。

在配置表列表上方的搜索框输入文件名可模糊筛选（忽略大小写，并支持按字符顺序匹配）。列表标题旁的“+”可新建带默认 `id` 字段的 TSV；删除按钮会在确认后删除当前打开的配置表。顶部不提供单独的“导入配置”按钮。

## 文件格式

- `.tsv` 文件使用 UTF-8 编码：第一行为字段名，第二行为数据类型，第三行为导出端，第四行为注释，第五行开始为数据。
- 左侧配置表列表支持新建与删除：桌面端会在所选配置目录中新建或永久删除 TSV；Android 端的新建和删除只作用于本次会话的配置表列表，不会修改手机原始文件。
- 每列可选择字符串、整数、小数、布尔值、JSON（对象/数组）、Lua 表数组或 Lua 表字典；导出端可选仅后端、仅前端或前后端，默认前后端。
- 字符串单元格中填写可访问的本地图片路径（支持 PNG、JPG、JPEG、GIF、WEBP、BMP）时，表格会显示小缩略图；点击该单元格即可查看和编辑原始路径。相对路径以当前 TSV 文件所在目录为基准。`test/test_config.tsv` 提供了图标路径示例。
- Lua 表数组输入 `{1, 2, "three"}`；Lua 表字典输入 `{id = 1, name = "道具"}` 或 `{["id"] = 1}`。支持嵌套表、字符串、数字、`true`、`false` 和 `nil`，不执行 Lua 代码；导出 JSON 时会转换为对应的数组或对象。
- 点击注释行可编辑说明，点击数据单元格可编辑数据；在表格工具栏打开“管理列”，可添加或删除字段，并配置新列的类型、导出端、注释和默认值。
- 每行最左侧的删除图标可删除对应数据行，删除前会请求确认；数据修改会进入当前会话的增量导出队列。
- 行操作步骤：先点击源行的行号，再点“复制行”或按 `Ctrl+C`；然后点击目标行的行号，再点“插入行”或按 `Ctrl+V`。副本会插入到目标行之前，目标行和其后的行顺序后移，不会覆盖原数据。按“撤销”或 `Ctrl+Z` 可撤销最近一次行排序、复制粘贴、新增/删除行或单元格编辑，最多保留 50 步。快捷键使用应用内行剪贴板，不会替代系统文本剪贴板。每行最左侧的拖动手柄可调整行顺序。
- 在“管理列”中删除字段前会请求确认，删除后会同时移除所有行中的该列数据。
- 点击表格工具栏的“导表规则”按钮可勾选当前配置表的 key 字段，默认选中 `id`（存在时）；多个 key 按表格列顺序逐层生成嵌套字典，取消所有 key 则导出为记录数组。
- 后端和前端分别选择导出目录及 Lua/JSON 文件格式，格式默认后端 Lua、前端 JSON。
- Lua 导出使用多行缩进格式：每条记录、字段及嵌套表分别换行，便于阅读和版本对比；TSV 单元格内的 Lua 表值仍保持单行。
- Lua 文件头会标注作者 `liter_wave`、生成工具和来源 TSV 文件名；TSV 没有工作表，因此不生成 Excel sheet 名称。
- 在“导出设置”中选择 TSV 配置文件目录，可查看该目录直接包含（不递归子目录）的配置表数量；左侧列表也会列出这些文件供打开。导出针对当前选中的配置表。
- 左侧搜索框支持文件名子序列模糊匹配，例如搜索 `skcf` 可匹配 `skill_config.tsv`；匹配不区分大小写。
- 导出目录、配置目录、前后端文件格式和各表导表规则会自动保存到本机应用设置（Windows：`%APPDATA%\GameConfigAssistant\settings.json`），重新打开应用后自动恢复。表格数据编辑和增量导出队列目前只保留在当前应用会话中，应用关闭后不会缓存，也不会写回源 TSV。
- 多 key 按 `[key1][key2]` 逐层生成嵌套字典，叶子保留完整记录。若 key 为空或组合重复，导出会报错；key 字段需要勾选对应导出端。
- 导出文件名直接使用 `<配置表名>.lua` 或 `<配置表名>.json`；前后端通过各自的导出目录区分，未选择对应导出端的列不会写入该端文件。若两端选择相同目录和格式，工具会提示文件名冲突并停止导出。
- “全量导出”会处理配置目录中的全部 TSV；“增量导出”会先列出本次应用会话中修改过的配置表供勾选，默认全选。未勾选的表会保留在增量队列中，勾选表导出成功后才从队列中移除；切换配置表会保留编辑内容。修改状态仅在当前应用会话中保留，且不会写回源 TSV 文件。
- 导出完成后会显示处理的配置表总数、生成文件总数，并逐表列出来源 TSV 及对应的导出文件路径。
- 新增行始终追加到整张表末尾，并自动跳转到新行所在分页。
