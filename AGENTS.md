# AGENTS.md - EnrollPilot 项目工作约定

## 项目卡片自动收尾

- 本项目对应卡片：`C:/Users/19845/Documents/resume-knowledge/projects/enrollpilot.md`
- 完成实质代码、架构、接口、算法、部署变更，或修复非平凡 bug 后，结束任务前必须执行
  `C:/Users/19845/.agents/skills/project-card/SKILL.md` 的工作流 A，不需要用户再说“更新卡片”。
- 先读现有卡片查重；只写代码、测试、文件、日志或用户口述能证实的事实；未落地标 `【设计中】`，
  不确定标 `【待补】`/`【待确认】`。
- 卡片改完后运行：

```bash
python "C:/Users/19845/.agents/skills/project-card/scripts/build_index.py" --if-stale
```

- 错别字、格式、注释、纯文案和无行为变化的小重构不触发。

## 项目约定

- 设计文档 `docs/报名结算系统-设计.md` 是唯一事实源：数据模型、双入口、
  结算口径（缴费 = 公司收费 + 返还）、分期都在里面，动代码先看它。
- 测试为纯脚本双模式：`python tests/test_xxx.py` 或 `pytest tests/`；
  新逻辑必须带离线测试（不依赖网络与飞书凭据）。
- 凭据只放 `config/enroll.yaml`（已 gitignore），示例在 `config/enroll.example.yaml`。
- 合规红线：只走飞书官方 API，绝不 hook 个人微信；证件照本地处理。
- 用项目虚拟环境的解释器运行：`.venv\Scripts\python.exe`。
