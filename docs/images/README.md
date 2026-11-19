# 截图目录

本目录下的 19 张图已由 `scripts/make_screenshots.py`（终端/表格）与 `scripts/capture_ui.py`（TuGraph 控制台实拍）生成，并通过 `scripts/embed_screenshots.py` 插入报告。重跑后按同样文件名覆盖、再重建 docx 即可。
截图建议：窗口宽度 ≥ 1000px，终端先执行 `$env:PYTHONIOENCODING="utf-8"` 避免乱码。

| 文件名 | 对应内容 | 复现命令 / 操作 |
|---|---|---|
| `01-tugraph-login.png` | TuGraph 控制台登录页（地址 127.0.0.1:7687） | 浏览器打开 `http://127.0.0.1:7070` |
| `02-connection-test.png` | 客户端连接三步请求与响应 | `python scripts/test_connection.py` |
| `03-env-check.png` | 环境自检表（正常项打勾） | `python scripts/00_check_env.py` |
| `04-init-schema.png` | 建 Schema 的 DDL 输出 | `python scripts/init_schema.py` |
| `05-clean-data.png` | 清洗后的 CSV | 打开 `data/clean/qa_clean.csv` |
| `06-ner-result.png` | 三种 NER 策略对比与分类型 F1 | `python scripts/01_preprocess.py` |
| `07-review-items.png` | 冲突项与待审核项 | 打开 `data/graph/review_items.csv` |
| `08-import-graph.png` | 入图阶段输出 | `python scripts/02_build_graph.py --mode rest` |
| `09-graph-list.png` | 登录后首页：图项目 medical_course_2026（93 点 / 138 边） | TuGraph Web 控制台 |
| `10-verify-graph.png` | 22 项验证全 PASS | `python scripts/03_verify_graph.py --mode rest` |
| `11-cypher-console.png` | 图查询面板执行 Cypher + 图谱视图 | 控制台 `#/query`，选图后执行 |
| `12-graph-quality.png` | 质量指标表 | `python scripts/02_build_graph.py --mode rest` 末段 |
| `13-llm-config.png` | 模型配置（Key 打码） | `.env` 与 `00_check_env.py` 的"大模型配置"一行 |
| `14-cli-demo.png` | 交互式多轮对话 | `python cli.py --mode rest` |
| `15-cli-transcript.png` | 13 场景对话记录 | `python scripts/04_ask.py --mode rest` |
| `16-eval-overall.png` | 三系统汇总表 | `python scripts/05_evaluate.py --mode rest` |
| `17-eval-bytype.png` | 分类型结果表 | 同上 |
| `18-eval-detail.png` | 失败样例明细 | 打开 `outputs/t2c_eval.csv` 筛 `correct=False` |
| `19-eval-json.png` | JSON 汇总 | 打开 `outputs/t2c_eval.json` |

> 没有 TuGraph 环境时，`--mode rest` 换成 `--mock`，输出结构一致，只是首行提示图库为离线模拟库。
> 若确实无法部署 TuGraph，请在报告中说明，并用 `--mock` 的输出配合 `test_connection.py` 的排错输出作为替代证据。