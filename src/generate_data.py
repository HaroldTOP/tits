# -*- coding: utf-8 -*-
"""合成清算数据生成器（可复现：固定随机种子）。

刻意注入 5 类「对账差异」，用于验证 sql/02_reconciliation.sql 的识别能力：

  1) MISSING     系统有、客户报表缺（漏数）
  2) DUPLICATE   客户报表同一交易编号出现两次（重复）
  3) ROUNDING    同一原始金额，系统四舍五入（ROUND_HALF_UP）、客户截断（TRUNC）
                 -> 相差恰好 1 分，属「舍入口径不同」
  4) TRUNCATION  客户侧金额比系统多 0.02 -> 相差 2 分，属「截断」
  5) MANUAL      客户侧比系统多 1.50 -> 相差 150 分，需人工核查

说明：这是「模拟数据」，不是任何真实机构的数据。
"""
import csv
import os
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

SEED = 20261019
N_TRADES = 2000
START = date(2026, 1, 1)
END = date(2026, 9, 30)

ACCOUNTS = ["A1001", "A1002", "A1003", "A1004", "A1005", "A1006"]
PRODUCTS = ["IRD", "OPT", "SWP", "TRS", "IDX"]

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")

D2 = Decimal("0.01")


def to_2(x: Decimal, mode=ROUND_HALF_UP) -> Decimal:
    return x.quantize(D2, rounding=mode)


def main():
    random.seed(SEED)
    os.makedirs(DATA_DIR, exist_ok=True)

    span = (END - START).days

    # ---------- 1. 生成系统侧原始明细（内部保留 4 位小数）----------
    trades = []
    for i in range(1, N_TRADES + 1):
        raw = Decimal(random.uniform(10_000, 3_000_000)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        trades.append(dict(
            trade_id="T%06d" % i,
            account_id=random.choice(ACCOUNTS),
            settle_date=(START + timedelta(days=random.randint(0, span))).isoformat(),
            raw=raw,
            direction="IN" if random.random() < 0.55 else "OUT",
            product_code=random.choice(PRODUCTS),
            status="PENDING" if random.random() < 0.03 else "SETTLED",
        ))

    # ---------- 2. 抽取缺陷样本（互不重叠）----------
    idx = list(range(N_TRADES))
    random.shuffle(idx)
    counts = [("missing", 12), ("duplicate", 15), ("rounding", 20),
              ("truncation", 18), ("manual", 6)]
    picks, cursor = {}, 0
    for name, n in counts:
        picks[name] = idx[cursor:cursor + n]
        cursor += n

    missing_set = set(picks["missing"])
    dup_set = set(picks["duplicate"])
    round_set = set(picks["rounding"])
    trunc_set = set(picks["truncation"])
    manual_set = set(picks["manual"])

    defects = []
    client_rows = []

    for i, t in enumerate(trades):
        # 系统侧金额：四舍五入到分
        sys_amount = to_2(t["raw"], ROUND_HALF_UP)
        t["amount"] = sys_amount

        # ① 漏数
        if i in missing_set:
            defects.append((t["trade_id"], "MISSING", 0.0))
            continue

        cli_amount = sys_amount

        if i in round_set:
            # ③ 舍入差异：客户用截断，系统用四舍五入
            #    若两者恰好相同，就微调原始值，保证「规则差异可观测」
            raw = t["raw"]
            guard = 0
            while to_2(raw, ROUND_DOWN) == to_2(raw, ROUND_HALF_UP) and guard < 200:
                raw = (raw + Decimal("0.001")).quantize(Decimal("0.0001"))
                guard += 1
            t["raw"] = raw
            sys_amount = to_2(raw, ROUND_HALF_UP)
            cli_amount = to_2(raw, ROUND_DOWN)
            t["amount"] = sys_amount
            defects.append((t["trade_id"], "ROUNDING",
                            float(sys_amount - cli_amount)))

        elif i in trunc_set:
            # ④ 截断：客户侧比系统多 0.007
            cli_amount = to_2(sys_amount + Decimal("0.020"))
            defects.append((t["trade_id"], "TRUNCATION", 0.02))

        elif i in manual_set:
            # ⑤ 人工核查级
            cli_amount = to_2(sys_amount + Decimal("1.50"))
            defects.append((t["trade_id"], "MANUAL", 1.50))

        row = dict(trade_id=t["trade_id"], account_id=t["account_id"],
                   settle_date=t["settle_date"], amount=cli_amount,
                   direction=t["direction"], product_code=t["product_code"])
        client_rows.append(row)

        # ② 重复
        if i in dup_set:
            client_rows.append(dict(row))
            defects.append((t["trade_id"], "DUPLICATE", 0.0))

    # ---------- 3. 落盘 ----------
    with open(os.path.join(DATA_DIR, "system_clearing.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["trade_id", "account_id", "settle_date", "amount",
                    "direction", "product_code", "status"])
        for t in trades:
            w.writerow([t["trade_id"], t["account_id"], t["settle_date"],
                        t["amount"], t["direction"], t["product_code"], t["status"]])

    random.shuffle(client_rows)
    with open(os.path.join(DATA_DIR, "client_clearing.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["trade_id", "account_id", "settle_date", "amount",
                    "direction", "product_code"])
        for r in client_rows:
            w.writerow([r["trade_id"], r["account_id"], r["settle_date"],
                        r["amount"], r["direction"], r["product_code"]])

    with open(os.path.join(DATA_DIR, "planted_defects.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["trade_id", "planted_defect", "diff"])
        w.writerows(defects)

    print("system rows :", len(trades))
    print("client rows :", len(client_rows))
    print("defects     :", len(defects))


if __name__ == "__main__":
    main()
