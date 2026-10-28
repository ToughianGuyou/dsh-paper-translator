# dsh-pdf-paper-translation-tools

为 DeepSeek Harness 提供 PDF 论文预检、分块读取、译文校验与重新排版。翻译由 Harness 当前 agent 完成；插件不调用额外翻译 API，也不需要新的 API Key。输入 PDF 始终保留。

这是有明确停止边界的首版实现，不能保证任意论文都能自动解析。请同时阅读 `TEST_REPORT.md`，以其中实际执行的验证为准。当前环境未接入你的 Harness 安装和真实模型会话，不能把离线测试当作你机器上的完整闭环验收。

## GitHub 下载与 dsh 市场发现

在仓库 Releases 下载 `.tgz` 安装包，安装后仍需配置 Python 环境和允许读取的论文目录。

```bash
dsh plugin --profile papers add ./dsh-pdf-paper-translation-tools-0.1.0.tgz
```

在 dsh 中启用实验性的自定义插件市场，打开“发现 → 添加索引源”，填写：

```text
https://raw.githubusercontent.com/ToughianGuyou/dsh-pdf-paper-translation-tools/main/market/index.json
```

添加后搜索 `dsh-pdf-paper-translation-tools`。该索引是本仓库维护的第三方索引，不代表官方审核或内置收录。市场安装固定到索引中的 Git 提交；仓库提交了 `lib/`，无需安装时构建。Python 依赖须按下文单独安装。

## 安装

需要 Python 3.10+、Node.js 22.13+ 与支持下述工具 API 的 DeepSeek Harness。入口按官方 `@deepseek-ai/dsh-tools@0.2.2-alpha.2` API 编写；请先检查 `dsh --version`，旧版本工具 API 不能假定兼容。注册表的 `latest` 标签可能仍指向较旧版本，开发依赖使用明确版本。

在解压的项目目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.txt
```

Windows 对应命令：

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r python\requirements.txt
```

包内已有 `lib/`，安装不需要编译。推荐先通过本地 overlay 加载，便于明确 Python 和文件目录：复制 `config.example.yml` 到自己的位置，填写插件 `lib/index.js`、Python 可执行文件、论文目录、工作目录与输出目录的绝对路径，然后启动：

```bash
dsh --patch /absolute/path/to/config.example.yml --dump-config
dsh --patch /absolute/path/to/config.example.yml
```

另一种方式是在包含解压目录的上级目录安装 bundle：

```bash
dsh plugin --profile papers add ./dsh-pdf-paper-translation-tools
dsh --profile papers --dump-config
dsh --profile papers
```

使用 bundle 时，需要在 profile 的 `cordis.patch.yml` 覆盖同一 id 的配置，尤其是 Python 路径与允许读取的目录。请依据你版本的官方配置说明填写覆盖条目；不要同时加载同名本地 overlay 与 bundle。默认 Python 是 PATH 中的 `python3`，其环境中必须安装依赖。配置变更支持 Harness 的插件热重载；不能确认热重载时，退出并用原启动命令重新启动。

查看五个工具是否出现：`pdf_prepare`、`pdf_read_blocks`、`pdf_submit_translations`、`pdf_export`、`pdf_job_status`。不出现时先检查插件加载日志、Harness 版本与 `tools` 服务。

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

`build` 只移除 TypeScript 类型，`typecheck` 独立执行类型检查。`npm pack` 产出带构建结果的 `.tgz`，可用 `dsh plugin --profile papers add ./dsh-pdf-paper-translation-tools-0.1.0.tgz` 安装。测试样本采用人工合成文本和图形，测试结果与未完成验收项见 `TEST_REPORT.md`。

## 依赖与许可

Python 核心依赖固定在 `python/requirements.txt`。PyMuPDF / MuPDF 使用 AGPL 或商业许可；将其集成、分发或作为服务部署时，应选择符合项目使用方式的许可。这个实现按 AGPL-3.0-or-later 提供，详见 `LICENSE`；不附带商业 MuPDF 授权。内置字体来源和实际使用字体可查看导出报告，替换字体前须核对字体授权。依赖安装需要网络，运行时无需额外模型下载。

## 接口依据

开发时核对官方文档和上游源码（2026-10-28）；这不等于核对了用户当前安装版本：

- https://deepseek-harness.github.io/deepseek-harness/develop/basic/tool
- https://deepseek-harness.github.io/deepseek-harness/develop/basic/config
- https://deepseek-harness.github.io/deepseek-harness/develop/basic/publish
- https://deepseek-harness.github.io/deepseek-harness/reference/cookbook/adding-a-tool
- https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/core/tools
