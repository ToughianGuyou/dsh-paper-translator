# dsh-pdf-paper-translation-tools

为 DeepSeek Harness 提供 PDF 论文预检、分块读取、译文校验与重新排版。翻译由 Harness 当前 agent 完成；插件不调用额外翻译 API，也不需要新的 API Key。输入 PDF 始终保留。

当前兼容修订版为 `0.1.1`，解析有明确的支持边界。已有合成 PDF、SDK 工具闭环及 GitHub CI 验证；尚未完成完整真实论文与真实模型会话验收。请阅读 [测试报告](./TEST_REPORT.md)，不要将离线测试等同于所有论文或所有 Desktop / Web 版本的兼容性保证。

## 安装

支持在 **DSH Desktop 客户端**或**DSH Web 服务端**安装。插件已发布到 [npm 官方源](https://www.npmjs.com/package/dsh-pdf-paper-translation-tools)，当前正式版为 `0.1.1`，包含 Desktop `0.2.1-rc.3` 的兼容修订。

安装分为两部分：**安装 npm 插件 → 配置 Python 环境和论文目录**。npm 包包含构建好的 `lib/`，正常使用不需要克隆源码、编译或执行 `npm publish`；npm 安装不会自动安装 Python 或 PyMuPDF。

### 运行要求

- Python 3.10+，并在插件使用的 Python 环境中安装 `PyMuPDF==1.26.6`。
- Node.js 22.13+（独立 CLI 环境）；Desktop 使用其随附运行环境，仍需单独提供 Python。
- 已配置模型、可使用工具的 DeepSeek Harness。`0.1.1` 的 SDK 闭环已针对 `0.2.1-rc.3` 和 `0.2.2-alpha.2` 验证；具体 Desktop 的完整模型翻译仍需本机验收。旧插件 `0.1.0` 的依赖范围不包含 `0.2.1-rc.3`，请勿强制绕过版本检查。
- 本插件提供五个 agent 工具，没有独立的翻译设置页面、PDF 上传页面或 OCR 功能。

### Desktop 客户端：安装兼容版本

Desktop `0.2.1-rc.3` 请安装 **`0.1.1` 或后续兼容版本**。npm 包和 GitHub Release 均已提供 `0.1.1`。

1. 打开 DSH Desktop，进入侧边栏的 **插件**，点击 **添加插件**。
2. 在“包名或地址”输入：

   ```text
   dsh-pdf-paper-translation-tools
   ```

3. “安装源”选择 **npm 官方源**，点击 **安装**。其他源可能有同步延迟；包名相同。界面文字随 Desktop 版本可能略有不同。
4. 在 **已安装** 中找到本插件，确认已启用。
5. 完成下方“首次配置”，再按宿主提示重启；必要时完整退出 Desktop（包括托盘）后重新打开。

有可用的 `dsh` 命令时，也可在终端安装到 Desktop 的 profile：

```powershell
dsh plugin --profile desktop add dsh-pdf-paper-translation-tools@0.1.1 --registry=https://registry.npmjs.org
```

终端找不到 `dsh` 时，使用上面的客户端安装入口即可。不要为了安装本插件另外创建 `papers` profile，然后误以为它已安装到 Desktop；插件属于所安装的 profile。

### Web 端：在运行 dsh 的机器上安装

在 **运行 DSH Web 的机器**上打开终端，执行：

```bash
dsh plugin --profile web add dsh-pdf-paper-translation-tools@0.1.1 --registry=https://registry.npmjs.org
```

完成“首次配置”后，重启原来的 Web 服务。使用标准 `web` profile 的实例通常以以下命令启动：

```bash
dsh web
```

如果使用自定义 profile、Docker、远程服务器或服务管理器，请沿用原有启动方式和 profile；上面的 `--profile web` 也要替换为实际 profile。Docker 中需在容器内安装 Python 依赖并挂载论文与输出目录。

**浏览器所在电脑的路径不等于服务器路径。** 例如浏览器在 Windows、dsh 在 Linux 服务器时，工具只能读取服务器上的文件；需要先将 PDF 放到服务器允许读取的目录，再提供服务器绝对路径。本插件本身不提供浏览器上传入口。

### 首次配置：Python 与文件目录（两端都需要）

以下命令均在 **插件实际运行的机器**上执行。推荐把 Python 虚拟环境放在插件包目录之外，避免插件升级时丢失。

#### Windows 示例

在 PowerShell 执行（盘符和目录可自行替换）：

```powershell
py -3 -m venv E:\dsh-paper-env
E:\dsh-paper-env\Scripts\python.exe -m pip install PyMuPDF==1.26.6

New-Item -ItemType Directory -Force E:\papers, E:\pdf-work, E:\pdf-output
E:\dsh-paper-env\Scripts\python.exe -c "import pymupdf; print(pymupdf.VersionBind)"
```

最后应打印 `1.26.6`。不必激活虚拟环境；后续直接配置 Python 可执行文件的绝对路径。

#### Linux / macOS 示例

```bash
python3 -m venv "$HOME/.venvs/dsh-paper"
"$HOME/.venvs/dsh-paper/bin/python" -m pip install PyMuPDF==1.26.6
mkdir -p "$HOME/papers" "$HOME/pdf-work" "$HOME/pdf-output"
"$HOME/.venvs/dsh-paper/bin/python" -c "import pymupdf; print(pymupdf.VersionBind)"
```

#### 写入对应 profile 的配置

编辑当前实例的 `$DSH_HOME/profiles/<profile>/cordis.patch.yml`：

| 宿主 | profile | 配置文件 |
| --- | --- | --- |
| 标准 Desktop | `desktop` | `$DSH_HOME/profiles/desktop/cordis.patch.yml` |
| 标准 Web | `web` | `$DSH_HOME/profiles/web/cordis.patch.yml` |
| 自定义实例 | 实际 profile 名 | `$DSH_HOME/profiles/<实际名称>/cordis.patch.yml` |

`$DSH_HOME` 表示此实例使用的 Harness 数据目录，不是要求原样粘贴的路径；未自定义时通常为用户目录下的 `.dsh`。Desktop 或启动器若指定了其他数据目录，以实际实例为准。若文件已有配置，**追加下面的列表条目，保留原有条目**。

npm 插件已安装后，用相同的 `id` 覆盖它的配置；这里不要再添加 `insert` 或源码入口路径。Windows 示例：

```yaml
- id: dsh-pdf-paper-translation-tools
  config:
    pythonExecutable: E:/dsh-paper-env/Scripts/python.exe
    keepOriginalMarkdown: true
    allowedInputDirectories:
      - E:/papers
    workDirectory: E:/pdf-work
    outputDirectory: E:/pdf-output
```

Linux / macOS 使用同一结构，把路径改成该机器的绝对路径，例如 `/home/you/.venvs/dsh-paper/bin/python`、`/home/you/papers`、`/home/you/pdf-work` 和 `/home/you/pdf-output`。不要在 YAML 中依赖 `~` 或 `$HOME` 自动展开；macOS 用户目录通常位于 `/Users/<用户名>`。

- `pythonExecutable` 必须指向刚安装 PyMuPDF 的 Python。
- `allowedInputDirectories` 是论文实际所在目录；插件会检查解析后的真实路径。
- `workDirectory` 保存恢复进度，`outputDirectory` 保存验证通过的交付结果。
- 相同 `id` 的配置会整体替换，需重述你要保留的自定义字段；未写出的字段使用插件默认值。
- `config.example.yml` 是**源码方式加载**的例子；不要把它和已安装的 npm bundle 同时加载。

保存后重启相应 Desktop / Web 宿主。独立 CLI 可先用 `dsh --profile web --dump-config` 检查最终配置（Desktop 对应 `desktop`；命令行与 Desktop 必须使用同一个数据目录）。

### 确认安装与第一次翻译

让 agent 列出是否可调用以下五个工具：

`pdf_prepare`、`pdf_read_blocks`、`pdf_submit_translations`、`pdf_export`、`pdf_job_status`。

然后将论文放入已配置目录，在对话中输入，例如：

> 请使用 PDF 论文翻译工具，将 E:/papers/paper.pdf 完整翻译成中文。先全文预检，再分批翻译和提交，保持所有保护标记；图表、图注和参考文献保留原文。全部完成并通过导出校验后，告诉我译文 PDF 的路径。如果预检失败，报告原因和页码并停止。

Linux / macOS 或远程 Web 请替换为相应的服务端路径。agent 应遵循 [AGENT_GUIDE.md](./AGENT_GUIDE.md)；无需用户手动逐个调用工具。译文在配置的 `outputDirectory` 对应任务目录中，通常包含 `translated.pdf`、`validation.json` 和可选的 `original.md`。远程服务的输出位于服务端，需通过该部署提供的文件访问方式取回。

### 可选：通过市场发现或离线安装

**自定义市场：** 启用 dsh 的实验性自定义插件市场，进入“发现 → 添加索引源”，填写：

```text
https://raw.githubusercontent.com/ToughianGuyou/dsh-pdf-paper-translation-tools/main/market/index.json
```

刷新后搜索 `dsh-pdf-paper-translation-tools`。当前索引使用 **npm 官方源的 0.1.1**，是本项目维护的第三方索引，不代表官方审核或内置收录；直接从 npm 添加插件无需添加索引。

**安装包：** 在 [Releases](https://github.com/ToughianGuyou/dsh-pdf-paper-translation-tools/releases) 下载 `.tgz`，在对应宿主机器上执行（Desktop 将 `web` 换为 `desktop`）：

```bash
dsh plugin --profile web add ./dsh-pdf-paper-translation-tools-0.1.1.tgz
```

这只能省去插件包的 npm 下载；Python 依赖仍需准备，并完成同样的首次配置。

### 常见问题

| 现象 | 检查方式 |
| --- | --- |
| npm 官方源能装，镜像源提示找不到 | 换 npm 官方源，确认包名带 `dsh-`；镜像可能尚未同步 |
| 已安装但 agent 看不到工具 | 检查启用状态、profile 和数据目录是否一致，重启宿主并查看加载日志 |
| `DEPENDENCY_MISSING` | 检查 `pythonExecutable`；用同一可执行文件运行 `-c "import pymupdf"` |
| 找不到 PDF 或目录未授权 | 使用宿主机器上的绝对路径，并确认位于 `allowedInputDirectories` 内 |
| 扫描件或复杂版面停止 | 当前无 OCR；按返回代码与页码处理，不能绕过停止状态冒充全文翻译 |


## 配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `keepOriginalMarkdown` | `true` | 生成独立原文 Markdown；设为 false 不影响分块和翻译 |
| `pythonExecutable` | `python3` | Python 可执行文件，推荐虚拟环境绝对路径 |
| `allowedInputDirectories` | `["."]` | 管理员授权的 PDF 目录，真实路径也须位于目录内 |
| `workDirectory` | `./work/dsh-pdf-paper-translation-tools` | 持久化任务与恢复数据 |
| `outputDirectory` | `./output/dsh-pdf-paper-translation-tools` | 验证通过的交付文件 |
| `fontPath` | 空字符串 | 可选字体文件路径；字体须有使用和嵌入许可 |
| `maxPages` | `300` | 输入页数上限 |
| `maxFileBytes` | `104857600` | 输入文件最大 100 MiB |
| `maxBatchSize` | `20` | 每批块数上限 |
| `timeoutMs` | `120000` | 单次工作进程超时 |
| `maxResponseBytes` | `8388608` | JSON 传输字节上限 |

相对路径以 Harness 启动时的工作目录为基准。输出名称由任务隔离，不能用工具参数关闭扫描拒绝、边界检查或物理尺寸保留。配置允许目录表示本地读取范围，不代表任意目录内文件都已得到用户授权；agent 只应处理用户指定文件。

## 处理规则与边界

- 仅处理可用文字层论文，无 OCR。扫描正文、混合扫描正文、隐藏 OCR 疑似扫描、乱码、无法确认的版面或资源边界会停止或进入检查状态。
- 单栏与典型双栏按区段恢复顺序；跨栏对象作为区段边界。复杂浮动框、多栏和无法确认的阅读顺序不应强行输出。
- 正文、标题、摘要翻译；作者、机构、邮箱等元数据默认保留原文，参考文献列表保留原文。标题/元数据识别与脚注关联的具体边界以测试报告为准。
- 图片、矢量图、表格及其图注/表注合并保留，图注不翻译。识别不明确时停止，不将表格内部文字交给 agent 重建。
- 独立公式按源区域保留；可识别的行内公式用保护标记映射到源区域，引用与脚注标记也受保护。无法可靠识别的数学边界进入检查状态；不宣称正则能识别所有数学表达式。
- 默认单栏重新排版，不保留原页数、栏数或原文字体。资源按原物理尺寸放置，必要时使用专用大页面。
- 默认交付原文 Markdown 和译文 PDF，不单独交付译文 Markdown。Markdown 不替代结构化数据；保留资源以占位引用表示。
- 目标语言是否受支持由字体与排版能力验证；未支持的复杂文字塑形/从右向左文字应明确拒绝。字符覆盖验证和结构验证不能证明翻译语义正确。
- 对重排后可能失效的原页码引用，报告提醒人工检查；不猜测新的页码。

## 使用与恢复

让 agent 阅读 `AGENT_GUIDE.md`。用户只需提供 PDF 路径和目标语言，例如：“把这篇论文完整翻译成中文，图表和图注保留原文。” agent 依次准备、读取、翻译、提交与导出。

任务中断后调用 `pdf_job_status`，使用返回版本和缺失块恢复。提交按稳定块 ID 校验；占位符丢失、增加、重复、未知块、过期版本或输入文件变化都拒绝。只有完整且通过输出验证的任务才返回正式译文文件路径。不能把失败状态下的临时文件作为译文交付。

`NEEDS_REVIEW` 表示需要解决版面/边界问题后重新预检，不能绕过继续翻译。`UNSUPPORTED_SCANNED_PDF` / `UNSUPPORTED_MIXED_PDF` 表示本插件不支持扫描正文；`TARGET_LANGUAGE_UNSUPPORTED` / `LAYOUT_UNSUPPORTED` 表示语言或排版不支持；`PDF_ENCRYPTED`、`PDF_INVALID`、`DEPENDENCY_MISSING` 分别表示文件或运行环境问题。`PLACEHOLDER_MISMATCH`、`STALE_VERSION` 与 `TRANSLATION_INCOMPLETE` 需要按状态结果修复，不可直接导出。

## 开发和验证

```bash
npm install
npm run build
npm run typecheck
npm test
python3 -m unittest discover -s tests -p 'test_*.py'
npm pack
```

`build` 只移除 TypeScript 类型，`typecheck` 独立执行类型检查。`npm pack` 产出带构建结果的 `.tgz`，可用 `dsh plugin --profile papers add ./dsh-pdf-paper-translation-tools-0.1.1.tgz` 安装。测试样本采用人工合成文本和图形，测试结果与未完成验收项见 `TEST_REPORT.md`。

## 依赖与许可

Python 核心依赖固定在 `python/requirements.txt`。PyMuPDF / MuPDF 使用 AGPL 或商业许可；将其集成、分发或作为服务部署时，应选择符合项目使用方式的许可。这个实现按 AGPL-3.0-or-later 提供，详见 `LICENSE`；不附带商业 MuPDF 授权。内置字体来源和实际使用字体可查看导出报告，替换字体前须核对字体授权。依赖安装需要网络，运行时无需额外模型下载。

## 接口依据

开发时核对官方文档和上游源码（2026-10-28）；这不等于核对了用户当前安装版本：

- https://deepseek-harness.github.io/deepseek-harness/develop/basic/tool
- https://deepseek-harness.github.io/deepseek-harness/develop/basic/config
- https://deepseek-harness.github.io/deepseek-harness/develop/basic/publish
- https://deepseek-harness.github.io/deepseek-harness/reference/cookbook/adding-a-tool
- https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/core/tools
