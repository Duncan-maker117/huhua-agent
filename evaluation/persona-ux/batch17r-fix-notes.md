# 第十七批 r：PDF 字体子集与预览超时

2026-10-19；工作树 `huhua-b17m`，分支 `batch17m`，HEAD `0a35e35`。在 m 的未提交改动之上实施，未 commit、push、部署、修改 dist，也未访问 8833/8834 或调用真实模型。

## 结论与证据边界

采用 **构建时生成常用字符 CFF 子集，运行时优先使用，完整系统 Noto CJK SC 负责回退**。不转换轮廓，不按样例收集字符，不改变 WeasyPrint 子集算法。七套模板公共样例在本机强制使用给定的 Debian 字体、强制走 fontTools 后，导出中位数为 **0.581–0.852 秒**；t001 从 **3.093 秒降至 0.688 秒，约 4.49 倍提速**。七套模板及独立字符覆盖探针的最大像素差均为 **0%**。

**这些不是生产 4 核 Linux 的优化后实测。** 本机为 macOS 26.6.2 / arm64 / Python 3.13.12，WeasyPrint 70.0、fontTools 4.66.1 与生产相同，原生 Pango/HarfBuzz、CPU 和系统环境不同。本机正常存在 HarfBuzz-Subset，基准进程显式禁用它，避免误用本机快路径。原始字体只读，SHA-256 见 `batch17r/font-build-manifest.json`，TTC 未复制进仓库。

用户提供的生产基线为 13.3 秒。按本机比值粗估约 2.96 秒，仅用于安排 Linux 验收，不能当成线上 ≤3 秒已达成。罕见字符触发完整字体时仍会变慢；独立混合字符探针为 2.283 → 3.016 秒，不承诺每份任意文字简历都达到公共样例速度。

## 根因

- 缺少 HarfBuzz-Subset 的环境走 WeasyPrint `_fonttools_subset`。每次导出处理巨大的 CFF 集合、保留 glyph ID、解子程序、去 hint、重算边界，CPU 成本集中于字体，而不是页面排版。
- m 的固定 15 秒子进程超时小于已知线上 14–40 秒正常耗时；两个槽均忙时立即 503，也会让七张画廊并发取图失败。
- 原 `lru_cache` 只缓存已完成调用，并不能合并同一模板的并发 cache miss；原发布也没有预先生成公共 PNG。

官方依据：[WeasyPrint 字体和选项说明](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html)、[fontTools subset 参数](https://fonttools.readthedocs.io/en/latest/subset/)。本次同时核对本机安装的 70.0 源码，未修改第三方包。

## 方案比较

下表均为 t001 + 仓库公共 sample。正式行取独立进程内 3 次渲染中位数；标 * 的探索项仅测一次，不据此断言小幅差异稳定。体积为 PDF 字节数；全字体大 PDF 移至临时目录，仅保留其大小、SHA-256 和原始测量记录。

| 方案 | 本机耗时 | PDF 字节 | 缺字/视觉风险 | 构建复杂度与选择 |
|---|---:|---:|---|---|
| 原 TTC + fontTools | 3.093s | 299,495 | 原字体覆盖边界 | 基线 |
| 原 TTC + `hinting=True` | 2.644s | 324,356 | 不缩覆盖；保留 hint 可能改变栅格外观 | 无构建成本，但提速不足 |
| 原 TTC + `full_fonts=True` | 2.051s | 32,006,501 | 不缩覆盖 | 无构建成本；超过现有 MCP 单文件 5 MiB 限制，不采用。生产证据为约 48 MB |
| 提取完整 SC CFF，预先去 hint/解子程序 * | 2.722s | 299,495 | 不缩覆盖 | 两个资产约 30.31 MB；构建约 38.27s，未解决大 glyph 空间成本 |
| 完整 SC → TrueType，cu2qu 最大误差 1 font unit * | 1.127s | 57,433 | 保留 44,810 个码点，但轮廓是近似转换；非零像素 2.3663%，通道差 >16 的像素 0.0193% | 两个资产约 39.55 MB；构建约 29.76s；比所选方案慢且不是像素一致，不采用 |
| **常用字符 CFF + 完整 SC 回退** | **0.688s** | **125,407** | **七模板和回退探针像素差 0%，保留原字形；罕见字符仍走慢路径** | **两个资产 7,526,904 字节（7.18 MiB），构建 13.19s；采用** |
| 常用 CFF 再提前去 hint * | 0.803s | 125,428 | 单页像素差 0% | 相比保留 hint 未见收益，不采用 |
| 常用 CFF 仅留 default/ZHS language shaping * | 0.607s | 112,828 | 单页像素差 0%，但缩减了其他语言 shaping 信息 | 小幅额外收益不足以承担语言支持边界，不采用 |
| 原 TTC + 本机 HarfBuzz-Subset | 0.092s | 299,038 | 不缩字体覆盖 | 仅对照；生产没有该库，本任务不新增下载依赖 |
| 公共模板 PNG 预生成 + 指纹/内存缓存 | 七图首次 0.034s；热缓存 0.00031s | 七图共 66,607 字节 | 只缓存公共样例，不缓存私人简历；版本不符回退渲染 | 现有依赖、构建约数秒，采用 |

探索原始记录：`batch17r/exploratory-results.json`。正式数据：`batch17r/benchmark/results.json`。

## 字体覆盖和视觉验证

`scripts/prepare_pdf_fonts.py` 根据字体 family 精确选择 SC face，不依赖 TTC 第几个 face 的固定索引；Regular 必须为 400，Bold 必须为 700。字符集合来自 Python 标准 GB2312 编码表，加 Latin、标点/符号、假名和全角 Unicode 范围，**与样例内容无关**。每个资产保留 8,302 个码点、14,374 个 glyph，保留原始 CFF 轮廓、水平度量、hint 和 layout features，并保留版权/许可证 name entries。

PDF CSS 的顺序为 `Huhua Resume CJK → Noto Sans CJK SC → sans-serif`。原系统 Regular/Bold TTC 继续保留；未命中子集的字符交给完整 SC 字体，再交给系统回退。子集并没有把字体能力永久截成 GB2312；源 SC 的 44,810 个码点仍可用。超出原字体和系统字体覆盖的 Unicode 不作全覆盖承诺。两份优化资产缺任意一份时整组停用，避免只安装 Regular 的不完整状态。

对照基准在隔离 fontconfig 中只加入指定 TTC 目录，所有模板明确强制 SC，防止 macOS PingFang 干扰。每个 PDF 用 Poppler 144 DPI 渲染为 RGB PNG，比较同位置任一 RGB 通道不同的像素占比；同时比较页数、提取文字、字体缺字表和实际 400/700 字重。

| 模板 | 原字体中位数 | 优化中位数 | PDF 字节：原 / 新 | 非零像素比例 |
|---|---:|---:|---:|---:|
| t001-jianyue | 3.093s | 0.688s | 299,495 / 125,407 | 0% |
| t002-jianyue | 2.789s | 0.625s | 299,136 / 125,222 | 0% |
| t003-shenlan | 2.759s | 0.581s | 317,234 / 125,128 | 0% |
| t004-jianyue | 2.385s | 0.852s | 325,754 / 125,886 | 0% |
| t1000 | 3.471s | 0.766s | 302,553 / 128,456 | 0% |
| t1001 | 2.571s | 0.614s | 299,028 / 124,940 | 0% |
| t1002-jianyue | 2.446s | 0.731s | 300,544 / 126,284 | 0% |

全部为一页，提取文字一致，实际嵌入 Regular 和 Bold，缺字列表为空。额外独立探针涵盖 CJK 扩展字符、生僻字、繁体、假名、符号和带重音 Latin，并同时放入常规/粗体位置：完整回退字体和优化字体均实际参与渲染，像素差仍为 0%，没有缺字。

- 七模板原/新 PDF 与 PNG：`batch17r/benchmark/sample/{baseline,prepared}/`。
- **最大差异比例：0%；差异图：`batch17r/benchmark/diffs/*-page1.png`**。白底红点表示差异，本次全部为白图；通道最大差也为 0。
- 回退探针：`batch17r/benchmark/coverage/`、`batch17r/benchmark/diffs/coverage-page1.png`。
- 人工检查七模板总览：`batch17r/seven-template-contact-sheet.png`；另放大检查 t001 和回退探针。无新增缺字、错重、重叠或版面漂移。

## 超时、排队与缓存

- `MCP_PREVIEW_TIMEOUT_SECONDS=90`：只计子进程执行，继续由 `subprocess.run(timeout=...)` 终止并回收超时子进程。设置为正数，可用环境变量覆盖。基于已知慢路径 40s × 2 + 10s 余量；不能因样例优化成功而压回 15s。线上优化后耗时尚未取得，暂不冒充已有生产安全系数实测。
- 并发上限仍是 **2**。公共模板预览允许排队，`MCP_PREVIEW_QUEUE_TIMEOUT_SECONDS=300`，覆盖七请求的最多三轮等待（3 × 90s + 30s）。队列超时才 503；单个私人简历预览保留两槽占满即 503，避免把任意内容计算请求堆成长队。
- 同模板用固定七个锁合并并发 miss，完成后沿用七条内存缓存；异常不缓存。冷画廊本机七请求并发 **4.610s，7/7 成功**，热缓存 **0.00031s**。
- 选择 **发布镜像构建时预热**，而非启动后额外争抢两个槽。`scripts/build_template_previews.py` 仅读取仓库公共样例，预生成七张 48 DPI PNG；不依赖模型、账号、数据库或网络。
- 新进程首次读预生成七图 **0.034s**。缓存指纹包括公共样例、模板、相关渲染代码、字体字节和 Python 渲染依赖版本；图片另有 SHA-256。内容过期、缺失或损坏时正常排队生成，成功后缓存。未正确 COPY 预生成资产的镜像仍有可用回退路径。
- 单张 MCP PDF→PNG（含子进程导入和启动）三次中位数：**原 2.830s → 新 1.034s**；三请求总墙钟 **5.980s → 2.319s**，第三个请求等待空槽。结果见 `batch17r/preview-results.json`。

## 改动与测试

- `backend/app/services/resume_pdf.py`、新增 `pdf_fonts.py`：统一让导出、测页和预览使用相同字体布局；新增两个固定内部 font URI 白名单，不开放任意文件/网络资源。
- `backend/app/config.py`、`.env.example`：字体目录、预览执行/排队超时、预生成 PNG 目录。
- `backend/app/services/mcp_preview.py`、`mcp_service.py`：可配置超时、公共模板排队、同模板合并、内存缓存。
- 新增 `template_previews.py`：构建资源指纹和图片哈希校验。
- 新增 `scripts/prepare_pdf_fonts.py`、`build_template_previews.py`、`benchmark_pdf_fonts.py`；`.gitignore` 排除生成字体，字体资产不进入源码仓库。
- `scripts/run_tests.py` 将公共预览缓存目录隔离到本轮临时目录：发布镜像已有 PNG 时，旧的渲染故障注入测试仍须实际经过渲染器；预生成缓存回归自行提供独立夹具。没有跳过或改弱旧断言。
- 新增 `tests/test_pdf_b17r.py` **11 项**：SC face 选择/源文件只读/400与700/覆盖和度量；不完整安装回退；启用字体后文件与网络访问仍拒绝；超时配置与默认慢路径余量；七请求最多两子进程；同模板并发只渲染一次；失败不缓存；排队超时不启动子进程；预生成图片和源码版本校验；字体改变令缓存失效。
- 既有 m 的“超时杀子进程并释放槽”“私人预览第三请求 503”“stderr 不泄露”断言保留，**本批没有修改或放宽任何旧测试断言**。没有新增依赖，没有改提示词或写作手册。
- 全量最终结果见下方验收记录；新增回归已 11/11 通过。Ruff 与 `git diff --check` 通过。

## 上线步骤（建议，未执行）

当前发布脚本使用 `FROM 线上镜像` 后 COPY 应用；只替换代码不会自动产生字体资产。将以下层插在 `Dockerfile.release` 原有代码 COPY 之后、`USER huhua` 之前；**本任务未改 dist 脚本**。

```dockerfile
# 上方沿用 FROM 当前线上镜像、USER root、原有 backend/app/main/web/templates COPY。
COPY data/sample_resume.json /app/data/sample_resume.json
COPY scripts/prepare_pdf_fonts.py scripts/build_template_previews.py /app/scripts/
RUN python /app/scripts/prepare_pdf_fonts.py \
      --source-dir /usr/share/fonts/opentype/noto --output-dir /app/data/fonts \
    && python /app/scripts/build_template_previews.py \
      --font-dir /app/data/fonts --output-dir /app/data/template_previews \
    && chmod -R a+rX /app/data/fonts /app/data/template_previews
USER huhua
```

不需要 `apt`、`pip install` 或 `fc-cache`：复用镜像现有字体与 fontTools，通过 PDF 内部 `@font-face` 加载。额外未压缩资产约 **7.53 MB 字体 + 67 KB PNG/manifest**，小于整套转 TTF；完整 TTC 必须继续保留。构建可使用 `--pull=false --network=none`；源字体缺失或格式/字重不符合时构建直接失败。不要把字体目录挂载到会被空数据卷覆盖的位置。

1. 隔离构建新镜像；将上述两个脚本加入构建上下文（不能只沿用旧的代码 COPY 清单）。已核对 `scripts/package_deploy.py` 的 allowlist 不包含根 `scripts/`，所以应把这两个文件加入本次构建/测试补充包；本批没有扩大原发布包的白名单。字体可在目标镜像内生成，也可先生成后 COPY；PNG 应在目标镜像内生成，以便指纹和原生渲染环境一致。
2. 在隔离 Linux 镜像内运行全量测试，检查真实退出码，不能使用 `|| true` 把失败当通过。
3. 在相同 4 核配额下运行 `scripts/benchmark_pdf_fonts.py`，源目录指定系统 Noto 目录、字体目录指定 `/app/data/fonts`，对 t001 和七模板复测。验收单页样例 ≤3s 级、七图文字和像素差、两槽并发、冷/热资源缓存，以及完整字体回退。基准 PNG 对比需要验收环境已有 Poppler；发布运行时不增加该依赖。
4. 验证默认超时为 90/300 秒、反向代理/客户端允许相应回退等待时间；正常首屏应命中构建 PNG。核对 mcp:preview 的异常仍是固定错误，不记录子进程私有正文。
5. 完成以上验收后再按已有发布流程切换镜像。本任务未执行切换。临时停用字体可设 `PDF_CJK_FONT_DIR=` 并重启；预生成缓存指纹随之不匹配，回到原字体，90 秒执行超时继续保留。

本机复现：

```sh
PY='/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python'
FONT_WORK=$(mktemp -d -t huhua-pdf-fonts)
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$PY" scripts/prepare_pdf_fonts.py \
  --source-dir /Users/yikuaibanz1/Desktop/sth/huhua-fonts --output-dir "$FONT_WORK/fonts"
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$PY" scripts/benchmark_pdf_fonts.py \
  --source-dir /Users/yikuaibanz1/Desktop/sth/huhua-fonts --font-dir "$FONT_WORK/fonts" \
  --output "$FONT_WORK/benchmark" --rounds 3
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$PY" scripts/build_template_previews.py \
  --font-dir "$FONT_WORK/fonts" --output-dir "$FONT_WORK/previews"
```

## 失败做法与未完成

- 全字体嵌入虽然省部分子集化开销，体积突破已有下载限制，不适合上线。
- 转 TTF 的第一版实验中 FontBuilder 从原 CFF font 推断 `isTTF=False`，`setupGlyf` 断言失败；实验明确设置 TrueType 模式后才完成比较。这条路线最终因更慢和非零像素差弃用，没有进入生产代码。
- 仅提取完整 SC face/提前去 hint，没有缩减巨大 glyph 空间，提速不足。删其他语言 shaping 不作为本次默认。
- 没有部署权限范围内的新生产实测；Linux 4 核验收、镜像实际构建和线上切换未执行。本机无可用 Docker CLI，不能声称已验证 Docker 层。
- 用户提到的另一笔 408ms HTTP 500 没有对应服务端异常证据，本批不能归因为超时或宣称已修复；如新镜像仍出现，需按请求关联日志单独定位。

## 最终验收记录

指定命令原样执行：

```sh
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "/Users/yikuaibanz1/Desktop/sth/huhua agent/.venv/bin/python" scripts/run_tests.py
```

最终 **2019 项，2017 通过、0 失败/错误、2 项既有跳过，104.575s**。跳过项均为 `tests/test_tailor_bench_private.py` 的原有私有样例检查，原因 `local private source not distributed`。没有新增跳过或放宽旧断言。完整日志 `/tmp/huhua-b17r-full-verified.log`；精简记录 `batch17r/test-results.txt`。

新增 11 项定向回归 11/11 通过。使用真实生成字体及已有构建 PNG 环境，再通过隔离测试运行器单跑 m 的超时/安全审计回归：1/1 通过（0.803s），说明预生成缓存不会遮蔽旧的故障断言。11 份本批 Python 文件 Ruff 与整体 diff 检查通过。

开场已有的 m 文件（除本批明确扩展的 `mcp_service.py`、`mcp_preview.py` 和仅追加的 mmr）SHA-256 均不变；两份源 TTC 哈希不变，仓库未新增字体二进制。七模板的完整 PNG 检查、独立字符回退检查和构建 PNG 读取均完成。未 commit/push/部署。
