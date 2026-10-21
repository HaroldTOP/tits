# -*- coding: utf-8 -*-
"""一键跑通：建库 -> 导入 CSV -> 执行对账 SQL -> 导出结果 CSV + 生成报告。

用法：
    python src/run.py
输出：
    data/reconciliation.db
    output/q1_missing.csv ... output/q6_totals.csv
    output/summary_report.md
"""
import os
import re
import sqlite3
import csv
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SQL_DIR = os.path.join(ROOT, "sql")
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "output")

DB_PATH = os.path.join(DATA_DIR, "reconciliation.db")

QUERY_NAMES = [
    "q1_missing",        # 漏数
    "q2_duplicates",     # 重复
    "q3_amount_diff",    # 金额差异定性
    "q4_running_total",  # 累计勾稽
    "q5_summary",        # 差异汇总
    "q6_totals",         # 双向总量
]


def read_sql(name):
    with open(os.path.join(SQL_DIR, name), encoding="utf-8") as f:
        return f.read()


def split_statements(text):
    """粗略按分号切语句，去掉纯注释段（本项目 SQL 内无分号出现在字符串里）。"""
    text = re.sub(r"--[^\n]*", "", text)
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def import_csv(conn, table, path):
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    placeholders = ",".join("?" * len(header))
    conn.executemany(
        f"INSERT INTO {table} ({','.join(header)}) VALUES ({placeholders})", rows
    )
    conn.commit()
    return len(rows)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")

    # 1) 建表
    for stmt in split_statements(read_sql("01_schema.sql")):
        conn.execute(stmt)
    conn.commit()

    # 2) 导入
    n_sys = import_csv(conn, "system_clearing",
                       os.path.join(DATA_DIR, "system_clearing.csv"))
    n_cli = import_csv(conn, "client_clearing",
                       os.path.join(DATA_DIR, "client_clearing.csv"))
    print(f"imported system_clearing={n_sys}, client_clearing={n_cli}")

    # 3) 跑对账
    stmts = split_statements(read_sql("02_reconciliation.sql"))
    results = {}
    for name, stmt in zip(QUERY_NAMES, stmts):
        cur = conn.execute(stmt)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        out_path = os.path.join(OUT_DIR, name + ".csv")
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        results[name] = dict(cols=cols, rows=rows, path=out_path)
        print(f"{name:<18} rows={len(rows):>4}  -> {out_path}")

    # 4) 与「注入的缺陷」对照，算识别率
    planted = {}
    with open(os.path.join(DATA_DIR, "planted_defects.csv"), encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            planted.setdefault(row["planted_defect"], set()).add(row["trade_id"])

    found = {
        "ROUNDING": {row[1] for row in results["q3_amount_diff"]["rows"]
                     if row[0] == "ROUNDING"},
        "TRUNCATION": {row[1] for row in results["q3_amount_diff"]["rows"]
                       if row[0] == "TRUNCATION"},
        "MANUAL": {row[1] for row in results["q3_amount_diff"]["rows"]
                   if row[0] == "MANUAL_REVIEW"},
        "MISSING": {row[1] for row in results["q1_missing"]["rows"]},
        "DUPLICATE": {row[1] for row in results["q2_duplicates"]["rows"]},
    }

    lines = []
    lines.append("# 对账结果摘要（自动生成）\n")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- 系统侧行数：{n_sys}")
    lines.append(f"- 客户侧行数：{n_cli}\n")
    lines.append("## 一、识别结果与注入缺陷的对照\n")
    lines.append("| 缺陷类型 | 注入数 | 检出数 | 识别率 |")
    lines.append("|---|---|---|---|")
    for kind in ["MISSING", "DUPLICATE", "ROUNDING", "TRUNCATION", "MANUAL"]:
        p = planted.get(kind, set())
        f = found.get(kind, set())
        hit = len(p & f)
        rate = (hit / len(p) * 100) if p else 0
        lines.append(f"| {kind} | {len(p)} | {len(f)} | {rate:.1f}% |")
    lines.append("")

    lines.append("## 二、差异汇总（Q5）\n")
    lines.append("| 差异类型 | 方向 | 笔数 | 金额差合计 |")
    lines.append("|---|---|---|---|")
    for row in results["q5_summary"]["rows"]:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    lines.append("")

    lines.append("## 三、总量勾稽（Q6）\n")
    cols = results["q6_totals"]["cols"]
    row = results["q6_totals"]["rows"][0]
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for c, v in zip(cols, row):
        lines.append(f"| {c} | {v} |")
    lines.append("")

    lines.append("## 四、结论\n")
    lines.append("- **舍入差异**（差 1 分、方向双向）与**截断差异**（差 2–9 分、多为单向）"
                 "可被规则自动定性，不需要逐笔人工看；")
    lines.append("- 差额 ≥ 10 分的记录统一归入 `MANUAL_REVIEW`，交人工核查；")
    lines.append("- 漏数与重复属于**结构性问题**，优先于金额差异处理——"
                 "因为一笔漏数会让后续所有累计勾稽全错。\n")

    report_path = os.path.join(OUT_DIR, "summary_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("report ->", report_path)

    conn.close()


if __name__ == "__main__":
    main()
