# DSH 论文 HTML 翻译工具

在 DeepSeek Harness 中翻译论文 HTML，输出可以离线打开的译文 HTML。保留原有 MathML / SVG 公式、图片、链接与页面结构，由 Harness 当前模型完成文字翻译。

npm 包名：`dsh-paper-translator`。当前版本：**0.2.2**。

## 功能

- 翻译标题、段落、图注、表内文字，保留参考文献与公式节点。
- 分批读取和提交译文；保存任务状态，支持中断后继续。
- 用占位符保护公式、引用和行内格式；检查标记数量及格式嵌套。
- 将支持的图片和样式资源嵌入输出，方便离线阅读。
- 输出 `translated.html` 与 `validation.json`。校验报告证明结构检查通过，不代表翻译语义准确。

公式不需要识别成 LaTeX，也不交给模型重写。源网页脚本不会执行。**本版主工作流不生成 PDF。**

## 安装

支持 DSH Desktop 客户端与 DSH Web 服务端。npm 安装不会自动安装 Python 依赖；插件没有独立上传或翻译设置页面。

### 从旧插件迁移（重要）

旧包 `dsh-pdf-paper-translation-tools` 与新包 `dsh-paper-translator` 是不同插件，不会自动迁移配置。

1. 安装新包后，禁用旧插件，避免重复注册同名工具。
2. 找到实际 profile 的 `cordis.patch.yml`。标准 Windows Desktop 通常位于 `C:\Users\<用户名>\.dsh\profiles\desktop\cordis.patch.yml`；自定义数据目录以实际实例为准。
3. 将旧配置条目的 `- id: dsh-pdf-paper-translation-tools` 改为 `- id: dsh-paper-translator`，保留其下已有的 `config`、论文、工作和输出目录。如果已存在新 ID 条目，合并到一条，避免重复。
4. 核对 `pythonExecutable` 是可运行的真实解释器绝对路径，并在**同一个解释器**中安装下方三个依赖。只有旧 ID 的配置不会应用于新插件，新插件会使用默认值。
5. 完整退出 Desktop（包括托盘）再重新打开；Web 重启实际服务。

配置中的 ID 必须是 `dsh-paper-translator`，不是包版本，也不是旧包名。

### Desktop 客户端

1. 打开侧边栏“插件”，选择“添加插件”。
2. 包名填写 `dsh-paper-translator`，安装源选择 **npm 官方源**。
3. 安装后确认插件已启用，完成下方 Python 与目录配置，再重启客户端。

如果有 `dsh` 命令，也可执行：

```powershell
dsh plugin --profile desktop add dsh-paper-translator@0.2.2 --registry=https://registry.npmjs.org
```

### Web 端

在实际运行 DSH Web 的机器上执行：

```bash
dsh plugin --profile web add dsh-paper-translator@0.2.2 --registry=https://registry.npmjs.org
```

完成配置后，沿用原来的方式重启 Web 服务。自定义 profile 请替换 `web`；Docker 部署需在容器内安装依赖并挂载文件目录。浏览器所在电脑的文件路径不是服务器文件路径。

### Python 与目录配置

要求 Python 3.10+；独立 Node 环境要求 Node.js 22.13+。SDK 依赖范围为 `0.2.1-rc.3` 或 `0.2.2-alpha.2` 兼容系列，完整桌面模型翻译仍需在实际安装环境验收。

Windows PowerShell 示例：

```powershell
py -3 -m venv E:\dsh-paper-env
E:\dsh-paper-env\Scripts\python.exe -m pip install PyMuPDF==1.26.6 beautifulsoup4==4.13.5 fonttools==4.61.1
New-Item -ItemType Directory -Force E:\papers, E:\html-work, E:\html-output
```

如果已经安装 Python 3.12，可直接使用该解释器，不必重复创建虚拟环境。在 PowerShell 执行：

```powershell
$paperPython = py -3.12 -c "import sys; print(sys.executable)"
& $paperPython -m pip install PyMuPDF==1.26.6 beautifulsoup4==4.13.5 fonttools==4.61.1
& $paperPython -c "import sys, pymupdf, bs4, fontTools; print(sys.executable); print('依赖正常')"
```

把打印出的真实路径写入 `pythonExecutable`。如果 `py` 不存在，直接使用已知的 `python.exe` 绝对路径。不要填写 `WindowsApps` 下会跳转 Microsoft Store 的 `python3` 存根。给另一个 Python 安装依赖不会修复插件正在使用的环境。

Linux / macOS 示例：

```bash
python3 -m venv "$HOME/.venvs/dsh-paper"
"$HOME/.venvs/dsh-paper/bin/python" -m pip install PyMuPDF==1.26.6 beautifulsoup4==4.13.5 fonttools==4.61.1
mkdir -p "$HOME/papers" "$HOME/html-work" "$HOME/html-output"
```

编辑实际实例的 `$DSH_HOME/profiles/<profile>/cordis.patch.yml`，在保留原有条目的前提下追加：

```yaml
- id: dsh-paper-translator
  config:
    pythonExecutable: E:/dsh-paper-env/Scripts/python.exe
    allowedInputDirectories:
      - E:/papers
    workDirectory: E:/html-work
    outputDirectory: E:/html-output
```

Desktop 通常使用 `desktop` profile，Web 通常使用 `web`。`$DSH_HOME` 表示实际 Harness 数据目录，未自定义时通常为用户目录下的 `.dsh`。Linux/macOS 请改为实际绝对路径；不要依赖 YAML 自动展开 `~` 或环境变量。Python 虚拟环境建议放在插件目录之外，避免升级时丢失。

配置后重启对应宿主。`config.example.yml` 是源码加载示例，不要和已安装的 npm bundle 同时加载。

## 使用

把论文 HTML 及资源放在允许目录中，例如 `E:/papers/paper.html`，然后告诉 agent：

> 请将 E:/papers/paper.html 完整翻译为中文 HTML。使用 html_prepare，分批翻译并提交所有待译块，完整保留保护标记及格式嵌套。完成后导出并告诉我 translated.html 的路径。遇到不支持的结构请报告，不要用部分译文冒充全文。

也支持用户明确授权的版本化链接：

```text
https://arxiv.org/html/论文编号v版本号
https://ar5iv.labs.arxiv.org/html/论文编号v版本号
```

例如路径必须包含 `v2` 等明确版本；远程资源限相同来源。请核对 HTML 的版本和内容完整性，不默认等同于某份 PDF。

### 工具流程

| 工具 | 用途 |
| --- | --- |
| `html_prepare` | 读取 HTML，检查资源并创建任务 |
| `pdf_read_blocks` | 分批读取尚未翻译的文字 |
| `pdf_submit_translations` | 按 blockId 提交译文 |
| `pdf_job_status` | 查看进度、缺失块及输出路径 |
| `pdf_export` | 对 HTML 任务输出 translated.html |

共享工具保留历史 `pdf_` 前缀以兼容已有调用；名称不表示 HTML 任务会转换成 PDF。另保留实验性的 `pdf_prepare`，它不是推荐的主流程，复杂 PDF 可能无法通过预检。

结果保存在 `outputDirectory/<jobId>/` 中。Web 部署的结果位于服务器，需通过部署提供的文件访问方式下载。操作约定见 [AGENT_GUIDE.md](./AGENT_GUIDE.md)。

## 环境诊断

`0.2.1` 在创建任务前检查实际 Python 版本与三个 Python 依赖。缺失或无法导入时，返回 `DEPENDENCY_MISSING`，包含实际 `pythonExecutable`、配置值、`missingPackages` 和针对该解释器的 `installCommand`；安装命令由用户执行，不会自动安装软件。

解释器启动失败、退出异常或没有返回 JSON 时，会显示配置的 Python 路径、正确插件 ID 与 Windows 路径排查方法。解释器根本没启动时，插件无法获知实际 Python 版本，也无法读取另一个插件 ID 下被忽略的配置；提示不是自动迁移或自动修复。

修改配置并安装依赖后重启 DSH，再重新调用 `html_prepare`。仍失败时保留完整错误代码和诊断字段供排查。

## Windows 中文编码修复（0.2.2）

`0.2.0` / `0.2.1` 的 Python 管道输出在 Windows 非 UTF-8 代码页下可能被 Node 错误解码，表现为中文正文、错误消息或输出路径含 `�`。这属于插件协议缺陷，不需要更改 Windows 系统代码页或改掉中文目录名。

`0.2.2` 的 worker 直接写 UTF-8 字节，bridge 同时固定 Python I/O 编码，并严格校验返回字节；非法 UTF-8 会返回 `WORKER_ENCODING_ERROR`，不再静默替换字符。编码回归测试覆盖 cp936/cp932/cp949/cp1251，Windows CI 也运行真实 worker 流程。

升级后必须完整退出 DSH（包括托盘）再打开，让新模块加载；只修改配置或刷新页面不一定重载插件代码。此前直接修改 node_modules 的临时补丁可由正式版本替代。

如果旧任务的待译文本已经乱码，并据此提交过译文，请重新创建任务并翻译；升级不能还原已损坏的译文。若只有显示路径损坏、磁盘文件内容正常，可升级后用原 jobId 查询状态，检查输出路径与文件内容。

## 支持范围与限制

- 需要可识别的 `article`、`main` 或 `.ltx_document` 正文，以及支持的段落、标题、列表、图注、表格结构。
- 支持已有 MathML、SVG 公式。仅含 `script type="math/tex"`、依赖执行脚本生成公式的页面暂不支持，需先准备 MathML / SVG 版本。
- 图片嵌入输出；远程 HTML 的同源 CSS 及其资源可嵌入。CSS `@import`、`srcset`、含资源引用的本地外部样式表、嵌入式交互内容暂不支持，遇到会要求检查。
- 本地资源必须位于源 HTML 所在目录或子目录中。外链字体、复杂布局和不同网站模板仍可能需要适配；不承诺任意网页通用。
- 不运行源网页脚本，因此交互功能不会保留。不提供 OCR、浏览器上传入口或额外翻译 API。
- 结构校验不能证明译文准确或视觉布局完全一致。当前已完成合成样本与 SDK 闭环测试，尚未完成 DDPM 全文 HTML 实际翻译验收。

## 市场与离线安装

npm 包发布不等于官方插件市场收录。可直接按包名从 npm 安装；本项目维护的第三方索引为：

```text
https://raw.githubusercontent.com/ToughianGuyou/dsh-paper-translator/main/market/index.json
```

GitHub [Releases](https://github.com/ToughianGuyou/dsh-paper-translator/releases) 可下载 `.tgz`，在宿主机器执行：

```bash
dsh plugin --profile web add ./dsh-paper-translator-0.2.2.tgz
```

Desktop 请换成 `--profile desktop`。离线插件包不包含 Python 解释器和 Python 依赖。

## 开发与许可

```bash
npm ci
python -m pip install -r python/requirements.txt
npm run build
npm run typecheck
npm test
npm run test:python
```

项目采用 AGPL-3.0-or-later；依赖说明见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)，验证范围见 [TEST_REPORT.md](./TEST_REPORT.md)。
