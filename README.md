# 医疗知识图谱对话系统

基于 TuGraph 4.x + 通义千问的中文医疗知识图谱问答实验：93 节点 / 138 边，Text2Cypher 端到端准确率 94.5%。

| 项目 | 内容 |
|---|---|
| 实验报告 | [在线阅读](docs/实验报告.md) |
| 图谱规模 | Disease 33 · Symptom 25 · Examination 18 · Drug 13 · Department 4 |
| 功能测试 | 73 条测例：可执行率 98.4%、执行准确率 95.3%、端到端准确率 94.5% |

## 快速开始

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env          # 填入 DASHSCOPE_API_KEY
python scripts/00_check_env.py       # 环境与 TuGraph 连通性检查
python scripts/02_build_graph.py --mode rest
python cli.py --mode rest            # 交互式问答
```

数据流：`data/raw` → `data/clean` → `data/graph` → TuGraph → `cli.py`；全流程命令见报告附录 A。

> 本仓库数据仅用于课程实验，未经医学核验，不能作为诊疗依据。