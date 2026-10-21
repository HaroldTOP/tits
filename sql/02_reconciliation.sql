-- ============================================================
-- 对账查询：5 个核心查询，覆盖「漏数 / 重复 / 金额差异 / 累计勾稽 / 汇总」
-- 文件：sql/02_reconciliation.sql
-- 用法：由 src/run.py 按顺序执行，每个查询以分号结尾
-- ============================================================

-- ------------------------------------------------------------
-- Q1 漏数：系统有、客户报表没有（LEFT JOIN + IS NULL）
-- ------------------------------------------------------------
SELECT
    'MISSING_IN_CLIENT'          AS diff_type,
    s.trade_id,
    s.account_id,
    s.settle_date,
    s.amount,
    s.direction,
    s.product_code
FROM system_clearing s
LEFT JOIN client_clearing c
       ON s.trade_id = c.trade_id
WHERE c.trade_id IS NULL
ORDER BY s.settle_date, s.trade_id;

-- ------------------------------------------------------------
-- Q2 重复行：客户报表里同一交易编号出现多次（GROUP BY + HAVING）
-- ------------------------------------------------------------
SELECT
    'DUPLICATE_IN_CLIENT' AS diff_type,
    c.trade_id,
    COUNT(*)              AS cnt,
    MIN(c.amount)         AS min_amount,
    MAX(c.amount)         AS max_amount
FROM client_clearing c
WHERE c.trade_id IS NOT NULL
GROUP BY c.trade_id
HAVING COUNT(*) > 1
ORDER BY cnt DESC, c.trade_id;

-- ------------------------------------------------------------
-- Q3 金额差异定性：舍入 / 截断 / 需人工核查（CASE WHEN）
-- 判定规则（单位：元）：
--   |diff| < 0.005  -> ROUNDING   （四舍五入口径不同）
--   |diff| < 0.01   -> TRUNCATION （截断导致，单向偏差）
--   其他            -> MANUAL     （不是舍入层的问题）
-- ------------------------------------------------------------
SELECT
    -- 关键：金额一律换算成「分」做整数比较，避免浮点误差
    --   相差 1 分   = 四舍五入口径不同（ROUNDING）
    --   相差 2-9 分 = 截断导致（TRUNCATION）
    --   相差 >= 10 分 = 不是舍入层的问题（MANUAL_REVIEW）
    CASE
        WHEN ABS(CAST(ROUND(s.amount * 100, 0) AS INTEGER)
               - CAST(ROUND(c.amount * 100, 0) AS INTEGER)) = 1 THEN 'ROUNDING'
        WHEN ABS(CAST(ROUND(s.amount * 100, 0) AS INTEGER)
               - CAST(ROUND(c.amount * 100, 0) AS INTEGER)) < 10 THEN 'TRUNCATION'
        ELSE 'MANUAL_REVIEW'
    END                          AS diff_type,
    s.trade_id,
    s.settle_date,
    s.amount                     AS system_amount,
    c.amount                     AS client_amount,
    ROUND(s.amount - c.amount, 4) AS diff,
    CASE WHEN s.amount > c.amount THEN 'SYSTEM_HIGHER'
         WHEN s.amount < c.amount THEN 'CLIENT_HIGHER'
         ELSE 'EQUAL' END        AS diff_direction
FROM system_clearing s
JOIN client_clearing c
  ON s.trade_id = c.trade_id
WHERE s.amount <> c.amount
ORDER BY ABS(s.amount - c.amount) DESC, s.trade_id;

-- ------------------------------------------------------------
-- Q4 累计勾稽：按日累计金额，定位「第一笔对不上的位置」
-- 思路：系统侧和客户侧各自按日期累计，逐日比对，差异首次非零即断点
-- ------------------------------------------------------------
WITH sys_daily AS (
    SELECT settle_date,
           SUM(amount) AS sys_amount
    FROM system_clearing
    GROUP BY settle_date
),
cli_daily AS (
    SELECT settle_date,
           SUM(amount) AS cli_amount
    FROM client_clearing
    WHERE trade_id IS NOT NULL
    GROUP BY settle_date
),
joined AS (
    SELECT d.settle_date,
           COALESCE(s.sys_amount, 0) AS sys_amount,
           COALESCE(c.cli_amount, 0) AS cli_amount
    FROM (SELECT DISTINCT settle_date FROM system_clearing
          UNION
          SELECT DISTINCT settle_date FROM client_clearing) d
    LEFT JOIN sys_daily s ON d.settle_date = s.settle_date
    LEFT JOIN cli_daily c ON d.settle_date = c.settle_date
)
SELECT settle_date,
       sys_amount,
       cli_amount,
       ROUND(sys_amount - cli_amount, 2)                        AS daily_diff,
       ROUND(SUM(sys_amount - cli_amount) OVER (ORDER BY settle_date), 2) AS running_diff
FROM joined
ORDER BY settle_date;

-- ------------------------------------------------------------
-- Q5 汇总：按差异类型和方向统计（给客户的结论层）
-- ------------------------------------------------------------
SELECT
    CASE
        WHEN ABS(CAST(ROUND(s.amount * 100, 0) AS INTEGER)
               - CAST(ROUND(c.amount * 100, 0) AS INTEGER)) = 1 THEN 'ROUNDING'
        WHEN ABS(CAST(ROUND(s.amount * 100, 0) AS INTEGER)
               - CAST(ROUND(c.amount * 100, 0) AS INTEGER)) < 10 THEN 'TRUNCATION'
        ELSE 'MANUAL_REVIEW'
    END                          AS diff_type,
    CASE WHEN s.amount > c.amount THEN 'SYSTEM_HIGHER'
         WHEN s.amount < c.amount THEN 'CLIENT_HIGHER' END AS diff_direction,
    COUNT(*)                     AS cnt,
    ROUND(SUM(s.amount - c.amount), 2) AS total_diff
FROM system_clearing s
JOIN client_clearing c ON s.trade_id = c.trade_id
WHERE s.amount <> c.amount
GROUP BY 1, 2
ORDER BY cnt DESC;

-- ------------------------------------------------------------
-- Q6 双向总量勾稽：系统总额 vs 客户总额 vs 差异
-- ------------------------------------------------------------
SELECT
    (SELECT ROUND(SUM(amount), 2) FROM system_clearing) AS system_total,
    (SELECT ROUND(SUM(amount), 2) FROM client_clearing WHERE trade_id IS NOT NULL) AS client_total,
    ROUND((SELECT SUM(amount) FROM system_clearing) - (SELECT SUM(amount) FROM client_clearing WHERE trade_id IS NOT NULL), 2) AS total_diff,
    (SELECT COUNT(*) FROM system_clearing)           AS system_rows,
    (SELECT COUNT(*) FROM client_clearing)           AS client_rows;
