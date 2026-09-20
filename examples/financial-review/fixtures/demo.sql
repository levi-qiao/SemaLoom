-- Invented values only. Run in an empty, isolated demo database.
-- CREATE without IF NOT EXISTS deliberately refuses to overwrite existing tables.
CREATE TABLE sample_taxpayer (
  tenant_id TEXT, id TEXT, name TEXT, PRIMARY KEY (tenant_id, id)
);
INSERT INTO sample_taxpayer VALUES
  ('tenant-a','C1','示例甲'), ('tenant-a','C2','示例乙'), ('tenant-a','C3','示例丙'),
  ('tenant-b','C1','另一租户企业');

CREATE TABLE sample_declaration (
  tenant_id TEXT, id TEXT, taxpayer_id TEXT, tax_year INTEGER,
  period_start DATE, period_end DATE, revenue NUMERIC, total_profit NUMERIC,
  taxable_income NUMERIC, income_tax NUMERIC, PRIMARY KEY (tenant_id, id)
);
INSERT INTO sample_declaration
SELECT 'tenant-a', 'D' || n || CASE WHEN year = 2024 THEN '' ELSE '-' || year END,
       'C' || n, year, make_date(year,1,1), make_date(year+1,1,1),
       100 + CASE WHEN n = 3 THEN 0 ELSE n * 0.01 END + (year-2024)*10,
       100 + CASE WHEN n = 3 THEN 0 ELSE n * 0.01 END + (year-2024)*10,
       90 + CASE WHEN n = 3 THEN 0 ELSE n * 0.01 END + (year-2024)*10, 20
FROM generate_series(1,3) AS n CROSS JOIN generate_series(2023,2025) AS year;
INSERT INTO sample_declaration VALUES
  ('tenant-b','D1','C1',2024,'2024-01-01','2025-01-01',999,999,999,20);

CREATE TABLE sample_audit_report (
  tenant_id TEXT, id TEXT, taxpayer_id TEXT, declaration_id TEXT,
  tax_year INTEGER, source_format TEXT, PRIMARY KEY (tenant_id, id)
);
INSERT INTO sample_audit_report
SELECT 'tenant-a','R' || n,'C' || n,'D' || n,2024,'PDF' FROM generate_series(1,3) AS n;
CREATE TABLE sample_financial_review (
  tenant_id TEXT, id TEXT, company_name TEXT, tax_year INTEGER,
  period_start DATE, period_to DATE, unique_pair BOOLEAN,
  declared_profit NUMERIC, audit_profit NUMERIC, net_profit NUMERIC,
  tax_expense NUMERIC, assets NUMERIC, liabilities NUMERIC, equity NUMERIC,
  company_id TEXT, report_id TEXT, return_id TEXT, pairing_policy TEXT,
  unit_basis TEXT, source_review_status TEXT, audit_profit_status TEXT,
  net_profit_status TEXT, tax_expense_status TEXT, assets_status TEXT,
  liabilities_status TEXT, equity_status TEXT, PRIMARY KEY (tenant_id, id)
);
INSERT INTO sample_financial_review
SELECT 'tenant-a', 'C' || n, name, 2024, DATE '2024-01-01', DATE '2025-01-01', true,
       profit, audit, net, 20, assets, 600, 400,
       'C' || n, 'R' || n, 'D' || n, 'LATEST_UPDATED_SAMPLE', '合成金额，人民币元',
       'unreviewed', CASE WHEN audit IS NULL THEN 'not_disclosed' ELSE 'observed' END,
       'observed', 'observed', CASE WHEN assets IS NULL THEN 'extraction_failed' ELSE 'observed' END,
       'observed', 'observed'
FROM (VALUES (1,'示例甲',100.01,100,80,1000), (2,'示例乙',100.02,100,79,1002),
             (3,'示例丙',100.00,NULL,80,NULL)) AS data(n,name,profit,audit,net,assets);

CREATE TABLE sample_audit_factor (
  tenant_id TEXT, id TEXT, report_id TEXT, factor_ref TEXT,
  value_current TEXT, value_prior TEXT, value_status_current TEXT, value_status_prior TEXT,
  PRIMARY KEY (tenant_id, id)
);
INSERT INTO sample_audit_factor
SELECT tenant_id, report_id || '-' || field, report_id, field,
       value::TEXT, NULL, status, 'not_evaluated'
FROM sample_financial_review CROSS JOIN LATERAL
  (VALUES ('profit',audit_profit,audit_profit_status), ('assets',assets,assets_status),
          ('netProfit',net_profit,net_profit_status), ('taxExpense',tax_expense,tax_expense_status),
          ('liabilities',liabilities,liabilities_status), ('equity',equity,equity_status))
  AS factor(field,value,status);
CREATE TABLE sample_declaration_line (
  tenant_id TEXT, id TEXT, declaration_id TEXT, line_number TEXT, amount NUMERIC,
  PRIMARY KEY (tenant_id, id)
);
INSERT INTO sample_declaration_line
SELECT tenant_id,id || '-1',id,'1',revenue FROM sample_declaration;
CREATE TABLE sample_mock_review (
  tenant_id TEXT, report_id TEXT, review_status TEXT, mocked BOOLEAN,
  PRIMARY KEY (tenant_id, report_id)
);
INSERT INTO sample_mock_review
SELECT tenant_id,id,'PENDING',true FROM sample_audit_report;
