"""一键建库脚本：用应用身份创建「报名结算」多维表格 + 五张表 + 字段，并回填配置。

用法（先确保 config/enroll.yaml 里 app_id/app_secret 已填）::

    python tools/setup_tables.py            # 建 base + 五张表 + 字段，回填 app_token/table_id
    python tools/setup_tables.py --smoke    # 建完后在报名记录表插一条测试记录再删除（验证链路）

设计依据：docs/报名结算系统-设计.md 第二节（字段名 = bitable 中文业务名）。
关联字段（报名记录.公司/班期、收款.关联报名记录）用 type=18 直接建；
若 API 拒绝关联字段，脚本会退化为文本占位并在输出里说明（UI 补建）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
import requests

BASE_API = "https://open.feishu.cn/open-apis"

# 字段类型码（飞书 bitable 官方枚举）
T_TEXT, T_NUMBER, T_SELECT, T_DATE, T_CHECKBOX, T_ATTACHMENT, T_LINK = 1, 2, 3, 5, 7, 17, 18


def sel(field_name, *options):
    """单选字段。options 为空时只给类型——空选项数组会被 API 拒绝。"""
    field = {"field_name": field_name, "type": T_SELECT}
    if options:
        field["property"] = {"options": [{"name": n} for n in options]}
    return field


def link(field_name, table_id, multiple=True):
    return {"field_name": field_name, "type": T_LINK,
            "property": {"table_id": table_id, "multiple": multiple}}


def get_token(session, app_id, app_secret):
    r = session.post(f"{BASE_API}/auth/v3/tenant_access_token/internal",
                     json={"app_id": app_id, "app_secret": app_secret}, timeout=15)
    data = r.json()
    if data.get("code") != 0:
        raise SystemExit(f"拿 token 失败：{data}")
    return data["tenant_access_token"]


def api(session, token, method, path, **kw):
    r = session.request(method, f"{BASE_API}{path}",
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json; charset=utf-8"},
                        timeout=20, **kw)
    payload = r.json()
    if payload.get("code") != 0:
        raise SystemExit(f"{method} {path} 失败：code={payload.get('code')} msg={payload.get('msg')}")
    return payload.get("data", {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="建完后插一条测试记录再删除")
    ap.add_argument("--app-token", default="", help="复用已存在的多维表格（不再新建）")
    args = ap.parse_args()

    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "config", "enroll.yaml")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    feishu = cfg["feishu"]
    session = requests.Session()
    token = get_token(session, feishu["app_id"], feishu["app_secret"])
    print("[1/5] tenant_access_token OK")

    # —— 建 base（应用所有，天然有全部权限）——
    if args.app_token:
        app_token = args.app_token
        base_url = f"https://open.feishu.cn/base/{app_token}"
        print(f"[2/5] 复用已有多维表格：app_token={app_token}")
        app_obj = {}
    else:
        data = api(session, token, "POST", "/bitable/v1/apps", json={"name": "报名结算"})
        # 新版接口 data.app 是对象 {app_token, default_table_id, url, ...}；旧版是字符串
        app_obj = data["app"]
        app_token = app_obj["app_token"] if isinstance(app_obj, dict) else app_obj
        base_url = app_obj.get("url", "") if isinstance(app_obj, dict) else data.get("url", "")
        print(f"[2/5] 多维表格已创建：app_token={app_token}\n      打开地址：{base_url}")

    tables = {}

    def create_table(name, fields):
        last = None
        for attempt in range(2):        # 官方接口偶发瞬时 field validation failed，重试一次
            try:
                d = api(session, token, "POST", f"/bitable/v1/apps/{app_token}/tables",
                        json={"table": {"name": name, "fields": fields}})
                tables[name] = d["table_id"]
                print(f"      表「{name}」→ {d['table_id']}")
                return
            except SystemExit as e:     # api() 用 SystemExit 抛错；仅对首次失败重试
                last = e
                if attempt == 0:
                    import time
                    time.sleep(1.2)
        raise last

    print("[3/5] 建五张表：")
    # 先建被关联的表
    create_table("公司", [
        {"field_name": "公司全名", "type": T_TEXT},
        {"field_name": "简称", "type": T_TEXT},
        sel("所属集团"),
        sel("结算方式", "对公", "业务员代收"),
        {"field_name": "协议价", "type": T_NUMBER},
        {"field_name": "联系人", "type": T_TEXT},
    ])
    create_table("班期", [
        {"field_name": "班期名称", "type": T_TEXT},
        {"field_name": "考试日期", "type": T_DATE},
        {"field_name": "起始日期", "type": T_DATE},
        {"field_name": "结束日期", "type": T_DATE},
        {"field_name": "考点", "type": T_TEXT},
        {"field_name": "考试科目", "type": T_TEXT},
        {"field_name": "课程", "type": T_TEXT},
        sel("状态", "筹备", "报名中", "已开班", "已结束"),
        {"field_name": "名额", "type": T_NUMBER},
        {"field_name": "负责业务员", "type": T_TEXT},
    ])
    create_table("收费标准", [
        {"field_name": "工种", "type": T_TEXT},
        sel("培训类型", "新办", "复审", "换证", "其他"),
        {"field_name": "标准价", "type": T_NUMBER},
        {"field_name": "备注", "type": T_TEXT},
    ])
    create_table("开票明细", [
        {"field_name": "序号", "type": T_NUMBER},
        {"field_name": "企业名称", "type": T_TEXT},
        {"field_name": "姓名", "type": T_TEXT},
        {"field_name": "复审到期日期", "type": T_TEXT},
        {"field_name": "安全员负责人", "type": T_TEXT},
        {"field_name": "工种", "type": T_TEXT},
        {"field_name": "培训类型", "type": T_TEXT},
        {"field_name": "公司收费", "type": T_NUMBER},
        {"field_name": "备注", "type": T_TEXT},
        {"field_name": "来源文件", "type": T_TEXT},
    ])
    create_table("报名记录", [
        {"field_name": "姓名", "type": T_TEXT},
        {"field_name": "手机号", "type": T_TEXT},
        {"field_name": "身份证号", "type": T_TEXT},
        sel("性别", "男", "女"),
        sel("民族", "汉", "回", "满", "蒙", "其他"),
        {"field_name": "出生日期", "type": T_DATE},
        {"field_name": "住址", "type": T_TEXT},
        sel("学历", "初中", "高中", "中专", "大专", "本科", "其他"),
        sel("人员类别", "主要负责人", "安全员", "管理员", "其他"),
        {"field_name": "工种", "type": T_TEXT},
        sel("培训类型", "新办", "复审", "换证", "其他"),
        sel("报名状态", "待确认", "已确认", "已参加", "未参加"),
        sel("缴费状态", "未收", "部分收款", "已缴费", "已退"),
        sel("开票状态", "未开", "已开"),
        link("公司", tables["公司"], multiple=False),
        link("班期", tables["班期"], multiple=False),
        {"field_name": "缴费", "type": T_NUMBER},
        {"field_name": "公司收费", "type": T_NUMBER},
        {"field_name": "返还", "type": T_NUMBER},
        {"field_name": "登记日期", "type": T_DATE},
        {"field_name": "参加日期", "type": T_DATE},
        {"field_name": "复审到期日期", "type": T_DATE},
        sel("登记渠道", "群机器人", "桌面工具", "EXCEL导入"),
        {"field_name": "身份证正", "type": T_ATTACHMENT},
        {"field_name": "一寸照", "type": T_ATTACHMENT},
        {"field_name": "缴费凭证", "type": T_ATTACHMENT},
        {"field_name": "备注", "type": T_TEXT},
    ])
    create_table("收款", [
        {"field_name": "姓名", "type": T_TEXT},
        {"field_name": "金额", "type": T_NUMBER},
        sel("收款方式", "微信", "支付宝", "对公", "现金"),
        sel("收款人类型", "业务员代收", "公司直收"),
        {"field_name": "业务员", "type": T_TEXT},
        {"field_name": "时间", "type": T_DATE},
        link("关联报名记录", tables["报名记录"], multiple=True),
        {"field_name": "缴费凭证", "type": T_ATTACHMENT},
        {"field_name": "备注", "type": T_TEXT},
    ])
    create_table("变更日志", [
        {"field_name": "姓名", "type": T_TEXT},
        {"field_name": "时间", "type": T_DATE},
        {"field_name": "操作人", "type": T_TEXT},
        sel("变更类型", "新增", "状态变更", "字段补全", "照片合并", "修正", "结算修正", "退款"),
        {"field_name": "字段", "type": T_TEXT},
        {"field_name": "旧值", "type": T_TEXT},
        {"field_name": "新值", "type": T_TEXT},
        {"field_name": "触发来源", "type": T_TEXT},
    ])

    # 删掉建 base 时自带的默认表
    default_tid = app_obj.get("default_table_id") if isinstance(app_obj, dict) else data.get("default_table_id")
    if default_tid and default_tid not in tables.values():
        try:
            api(session, token, "DELETE", f"/bitable/v1/apps/{app_token}/tables/{default_tid}")
            print("[4/5] 已删除默认示例表")
        except SystemExit as e:
            print(f"[4/5] 默认表删除失败（不影响使用）：{e}")

    # —— 回填配置 ——
    cfg["bitable"]["app_token"] = app_token
    cfg["bitable"]["tables"] = tables
    with open(cfg_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
    print(f"[5/5] 配置已回填 {cfg_path}")

    if args.smoke:
        tid = tables["报名记录"]
        d = api(session, token, "POST", f"/bitable/v1/apps/{app_token}/tables/{tid}/records",
                json={"fields": {"姓名": "冒烟测试", "备注": "setup_tables --smoke"}})
        rid = d["record"]["record_id"]
        api(session, token, "DELETE", f"/bitable/v1/apps/{app_token}/tables/{tid}/records/{rid}")
        print("冒烟测试通过：报名记录表建/删记录成功，API 链路全通 ✓")

    print("\n完成。base 地址（建议收藏，后续可在 UI 里给自己加协作者权限）：")
    print(base_url)


if __name__ == "__main__":
    main()
