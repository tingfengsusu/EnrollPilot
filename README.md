# EnrollPilot — 培训报名结算助手（飞书）

把「前台微信收图 → 手工攒 Excel → 群里口头改状态 → 月底人工核结算表」换成一条自动链路，
**主库是飞书多维表格**（双入口，一个库）：

```
入口A（主，无人值守）：微信照片 →（转发）→ 飞书群 → 机器人收图 → OCR/LLM 抽取
                      → 写/并 报名记录 → 群里回执卡片
入口B（补充，M2）：微信里复制图片 → 桌面工具自动读剪贴板 → OCR/LLM 清洗
                  → 人眼预览 → 写同一张报名表（exe）
```

一句话看它现在能干什么（离线、不联网、不需要凭据）：

```bash
.venv\Scripts\python tools\enroll_bot.py --demo
```

跑的是真实业务函数：种子数据 → 「张莹 已缴费 700」（改状态+落流水+写变更日志）→
「李蕾 已退」→「记录 张莹」（审计时间线）→「结算」（日报：公司应留存 / 待收 / 差异红灯）。

## 项目结构

| 目录 | 内容 |
|---|---|
| `docs/报名结算系统-设计.md` | **唯一设计事实源**（数据模型/双入口/结算口径/分期） |
| `gateway/` | 飞书长连接接入（自 FormPilot 迁移：收消息、下载附件、多事件合并） |
| `core/` | 纯逻辑基建（自 FormPilot 迁移：身份证校验位、字典别名归一化） |
| `enroll/` | 业务层：`bitable.py` 多维表格客户端 / `records.py` 幂等合并 / `instructions.py` 群指令 / `settlement.py` 结算核对 / `demo_store.py` 离线库 / `service.py` 指令执行 |
| `tools/enroll_bot.py` | CLI：`--demo` 离线闭环 / `--check-config` 配置体检 |
| `config/enroll.example.yaml` | 配置模板（正式 `enroll.yaml` 已 gitignore） |

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest tests/ -q     # 全部离线测试
.venv\Scripts\python tools\enroll_bot.py --demo
```

测试为**纯脚本双模式**：`python tests/test_xxx.py` 或 `pytest tests/` 均可，
不依赖网络与凭据。

## 实施阶段

- **M1（进行中）**：bitable 客户端 + 记录幂等合并 + 群指令 + 结算核对 —— **离线地基 ✅**
- **M1 联调**（需凭据）：① 飞书开放平台建企业自建应用（长连接 + `im:message`/`im:resource`/`bitable:app`）；
  ② 按设计文档**手动建五张表**（bitable API 建不了关联字段，须 UI 建）并授权应用；
  ③ `cp config/enroll.example.yaml config/enroll.yaml` 填凭据与表 id（`--check-config` 体检）；
  ④ 群机器人收图落表 + 回执（收图抽取方案见设计文档 2.0 微信识别实测）。
- **M2**：桌面剪贴板入口（PyQt5 精简入口 + QClipboard 双模式：图片走 OCR、文本走 LLM 清洗）+ exe
- **M3**：变更日志三处浮现（群卡片 / 查询指令 / 面板时间线）——日志表与 `records.py` 已就绪
- **M4**：收款表联调 + 结算日报自动推送 + 名单导出（替代旧表三张手工衍生表）
- **P2**：班期驱动的消息提醒、对着报名数据的问答机器人

## 合规边界

只走飞书官方 API，**绝不 hook 个人微信**（微信只做"复制/转发"一步人肉搬运）；
身份证等证件照本地处理；变更日志只记字段级事实；提交/收款的真实资金动作永远由人完成。
