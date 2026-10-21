-- ============================================================
-- 清算数据对账与异常检测
-- 文件：sql/01_schema.sql
-- 说明：建表语句（SQLite 方言，MySQL 需把 TEXT/REAL 换成 VARCHAR/DECIMAL）
-- ============================================================

DROP TABLE IF EXISTS system_clearing;
DROP TABLE IF EXISTS client_clearing;

-- 系统侧清算流水（我方系统）
CREATE TABLE system_clearing (
    trade_id     VARCHAR(32) PRIMARY KEY,   -- 交易编号（业务主键）
    account_id   VARCHAR(32) NOT NULL,      -- 资金账户
    settle_date  DATE        NOT NULL,      -- 清算日期
    amount       DECIMAL(18,2) NOT NULL,    -- 清算金额（保留 2 位）
    direction    VARCHAR(3)  NOT NULL,      -- IN=收 / OUT=付
    product_code VARCHAR(16) NOT NULL,      -- 产品代码
    status       VARCHAR(8)  NOT NULL       -- SETTLED=已清算 / PENDING=待清算
);

-- 客户报表侧清算流水（客户 Excel 导出）
CREATE TABLE client_clearing (
    trade_id     VARCHAR(32),               -- 故意不设主键：客户报表可能有重复行
    account_id   VARCHAR(32) NOT NULL,
    settle_date  DATE        NOT NULL,
    amount       DECIMAL(18,2) NOT NULL,
    direction    VARCHAR(3)  NOT NULL,
    product_code VARCHAR(16)
);

CREATE INDEX idx_sys_date   ON system_clearing(settle_date);
CREATE INDEX idx_sys_acct   ON system_clearing(account_id);
CREATE INDEX idx_cli_date   ON client_clearing(settle_date);
CREATE INDEX idx_cli_acct   ON client_clearing(account_id);
CREATE INDEX idx_cli_trade  ON client_clearing(trade_id);
