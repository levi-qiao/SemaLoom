-- Source-contract amounts are normalized CNY; extraction is not independently audited here.
-- Aggregate values are used only when exactly one factor row exists (no hidden first/last).
CREATE OR REPLACE VIEW sample_financial_review AS
WITH factors AS (SELECT tenant_id,report_id,
CASE WHEN count(*) FILTER (WHERE factor_ref='income_statement.total_profit')=1 THEN min(numeric_current) FILTER (WHERE factor_ref='income_statement.total_profit') END AS audit_profit,
CASE WHEN count(*) FILTER (WHERE factor_ref='income_statement.total_profit')>1 THEN 'ambiguous' ELSE coalesce(min(value_status_current) FILTER (WHERE factor_ref='income_statement.total_profit'),'missing') END AS audit_profit_status,
CASE WHEN count(*) FILTER (WHERE factor_ref='income_statement.net_profit')=1 THEN min(numeric_current) FILTER (WHERE factor_ref='income_statement.net_profit') END AS net_profit,
CASE WHEN count(*) FILTER (WHERE factor_ref='income_statement.net_profit')>1 THEN 'ambiguous' ELSE coalesce(min(value_status_current) FILTER (WHERE factor_ref='income_statement.net_profit'),'missing') END AS net_profit_status,
CASE WHEN count(*) FILTER (WHERE factor_ref='income_statement.income_tax_expense')=1 THEN min(numeric_current) FILTER (WHERE factor_ref='income_statement.income_tax_expense') END AS tax_expense,
CASE WHEN count(*) FILTER (WHERE factor_ref='income_statement.income_tax_expense')>1 THEN 'ambiguous' ELSE coalesce(min(value_status_current) FILTER (WHERE factor_ref='income_statement.income_tax_expense'),'missing') END AS tax_expense_status,
CASE WHEN count(*) FILTER (WHERE factor_ref='balance_sheet.total_assets')=1 THEN min(numeric_current) FILTER (WHERE factor_ref='balance_sheet.total_assets') END AS assets,
CASE WHEN count(*) FILTER (WHERE factor_ref='balance_sheet.total_assets')>1 THEN 'ambiguous' ELSE coalesce(min(value_status_current) FILTER (WHERE factor_ref='balance_sheet.total_assets'),'missing') END AS assets_status,
CASE WHEN count(*) FILTER (WHERE factor_ref='balance_sheet.total_liabilities')=1 THEN min(numeric_current) FILTER (WHERE factor_ref='balance_sheet.total_liabilities') END AS liabilities,
CASE WHEN count(*) FILTER (WHERE factor_ref='balance_sheet.total_liabilities')>1 THEN 'ambiguous' ELSE coalesce(min(value_status_current) FILTER (WHERE factor_ref='balance_sheet.total_liabilities'),'missing') END AS liabilities_status,
CASE WHEN count(*) FILTER (WHERE factor_ref='balance_sheet.total_equity')=1 THEN min(numeric_current) FILTER (WHERE factor_ref='balance_sheet.total_equity') END AS equity,
CASE WHEN count(*) FILTER (WHERE factor_ref='balance_sheet.total_equity')>1 THEN 'ambiguous' ELSE coalesce(min(value_status_current) FILTER (WHERE factor_ref='balance_sheet.total_equity'),'missing') END AS equity_status,
string_agg(DISTINCT coalesce(source_review_status,'unknown'),',' ORDER BY coalesce(source_review_status,'unknown')) AS source_review_status
FROM sample_audit_factor GROUP BY tenant_id,report_id)
SELECT r.tenant_id,r.id,r.id AS report_id,r.declaration_id AS return_id,
r.taxpayer_id AS company_id,c.name AS company_name,r.tax_year,
d.period_start,(d.period_end + 1) AS period_to,
d.total_profit AS declared_profit,
r.declaration_candidates,r.report_candidates,
(r.declaration_candidates=1 AND r.report_candidates=1) AS unique_pair,
'LATEST_UPDATED_SAMPLE'::text AS pairing_policy,
'UPSTREAM_CNY_CONTRACT'::text AS unit_basis,
coalesce(f.source_review_status,'unknown') AS source_review_status,
f.audit_profit,
f.net_profit,
f.tax_expense,
f.assets,
f.liabilities,
f.equity,
f.audit_profit_status,
f.net_profit_status,
f.tax_expense_status,
f.assets_status,
f.liabilities_status,
f.equity_status
FROM sample_audit_report r
JOIN sample_declaration d ON d.tenant_id=r.tenant_id AND d.id=r.declaration_id
JOIN sample_taxpayer c ON c.tenant_id=r.tenant_id AND c.id=r.taxpayer_id
LEFT JOIN factors f ON f.tenant_id=r.tenant_id AND f.report_id=r.id;
