import { array, object, text } from "./doc";
import type { DraftDocument } from "./types";

export function SheetHelp({ title, body }: { title: string; body: string }) {
  return (
    <div className="sheet-help">
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

export function AboutSidePanel({
  document,
  documents,
  onOpenEntity,
}: {
  document: DraftDocument;
  documents: DraftDocument[];
  onOpenEntity?: (id: string) => void;
}) {
  const properties = array(document.properties) as Record<string, unknown>[];
  const identityKeys = array(document.identityKeys).map(String);
  const mappings = documents.filter((item) => item.kind === "Mapping" && item.target === document.id);
  const links = documents.filter(
    (item) => item.kind === "Link" && (item.source === document.id || item.target === document.id),
  );
  const metricIds = new Set(
    documents.filter((item) => item.kind === "Metric" && item.objectType === document.id).map((item) => item.id),
  );
  const rules = documents.filter(
    (item) =>
      item.kind === "Rule" &&
      array(item.inputs).some((input) => {
        const row = input as Record<string, unknown>;
        return row.objectType === document.id || (typeof row.metric === "string" && metricIds.has(row.metric));
      }),
  );
  const actions = documents.filter((item) => item.kind === "Action" && item.targetObject === document.id);

  const outgoing = links.filter((l) => l.source === document.id);
  const incoming = links.filter((l) => l.target === document.id);
  const numericCount = properties.filter((p) => text(p.valueType) === "DECIMAL").length;
  const missingUnitCount = properties.filter((p) => text(p.valueType) === "DECIMAL" && !text(p.unit)).length;

  return (
    <div className="ontology-side-panel">
      <SheetHelp
        title="概况"
        body="名称给人和 AI 看；语义 ID 一旦发布就不要改。属性和表字段的对应在「属性与来源」。"
      />

      <div className="ontology-side-card">
        <div className="ontology-card-title">
          <span>业务身份 (Object Identity)</span>
          <span className="ontology-tag">{identityKeys.length ? "已定义主键" : "缺主键"}</span>
        </div>
        <p className="ontology-desc">
          在租户及对象类型内唯一标识一个对象。同名字段不构成相同身份，跨源查询严格通过主键与声明的关系对齐。
        </p>
        <div className="ontology-badge-row">
          <span className="ontology-badge primary">
            {identityKeys.length ? `🔑 主键已定义 (${identityKeys.length})` : "🔑 暂缺主键"}
          </span>
          <span className="ontology-badge code">域：{document.id.split(".")[0]}</span>
        </div>
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">本体特征速览</div>
        <div className="ontology-stats-grid">
          <div className="ontology-stat-box">
            <span className="ontology-stat-label">属性总数</span>
            <strong className="ontology-stat-val">{properties.length}</strong>
            <small className="ontology-stat-hint">测量槽 {numericCount}</small>
          </div>
          <div className="ontology-stat-box">
            <span className="ontology-stat-label">物理映射</span>
            <strong className="ontology-stat-val">{mappings.length}</strong>
            <small className="ontology-stat-hint">表/接口来源</small>
          </div>
          <div className="ontology-stat-box">
            <span className="ontology-stat-label">关联关系</span>
            <strong className="ontology-stat-val">{links.length}</strong>
            <small className="ontology-stat-hint">出 {outgoing.length} · 入 {incoming.length}</small>
          </div>
          <div className="ontology-stat-box">
            <span className="ontology-stat-label">业务判断</span>
            <strong className="ontology-stat-val">{rules.length}</strong>
            <small className="ontology-stat-hint">操作 {actions.length}</small>
          </div>
        </div>
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">关联实体网络</div>
        {links.length ? (
          <ul className="ontology-link-list">
            {outgoing.map((link) => {
              const targetId = text(link.target);
              const targetDoc = documents.find((d) => d.id === targetId && d.kind === "ObjectType");
              const label = text(targetDoc?.label) || targetId;
              return (
                <li key={link.id} className="ontology-link-item">
                  <div className="link-meta">
                    <span className="direction-tag out">出边</span>
                    <strong>{label}</strong>
                    <code>{targetId}</code>
                  </div>
                  {onOpenEntity ? (
                    <button className="text-link" onClick={() => onOpenEntity(targetId)}>查看</button>
                  ) : null}
                </li>
              );
            })}
            {incoming.map((link) => {
              const sourceId = text(link.source);
              const sourceDoc = documents.find((d) => d.id === sourceId && d.kind === "ObjectType");
              const label = text(sourceDoc?.label) || sourceId;
              return (
                <li key={link.id} className="ontology-link-item">
                  <div className="link-meta">
                    <span className="direction-tag in">入边</span>
                    <strong>{label}</strong>
                    <code>{sourceId}</code>
                  </div>
                  {onOpenEntity ? (
                    <button className="text-link" onClick={() => onOpenEntity(sourceId)}>查看</button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="ontology-hint">暂未配置关联实体。可在「关系」页签声明与其它实体的业务关联。</p>
        )}
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">本体就绪检查</div>
        <ul className="ontology-checklist">
          <li className={identityKeys.length ? "is-ok" : "is-warn"}>
            <span className="check-mark">{identityKeys.length ? "✓" : "!"}</span>
            <span>业务身份键：{identityKeys.length ? `已指定 ${identityKeys.length} 个主键字段` : "未配置业务主键"}</span>
          </li>
          <li className={mappings.length ? "is-ok" : "is-warn"}>
            <span className="check-mark">{mappings.length ? "✓" : "!"}</span>
            <span>物理映射：{mappings.length ? `已绑定 ${mappings.length} 个事实来源` : "尚未配置表/接口映射"}</span>
          </li>
          <li className={missingUnitCount === 0 ? "is-ok" : "is-warn"}>
            <span className="check-mark">{missingUnitCount === 0 ? "✓" : "!"}</span>
            <span>测量槽规范：{missingUnitCount === 0 ? "金额与数量已标注单位" : `${missingUnitCount} 个数值属性缺失单位`}</span>
          </li>
          <li className={rules.length ? "is-ok" : "is-info"}>
            <span className="check-mark">{rules.length ? "✓" : "i"}</span>
            <span>业务规则覆盖：{rules.length ? `已配置 ${rules.length} 项判断` : "暂无规则（可按需补充）"}</span>
          </li>
        </ul>
      </div>
    </div>
  );
}

export function RelationsSidePanel({
  document,
  documents,
  links,
  onOpenEntity,
}: {
  document: DraftDocument;
  documents: DraftDocument[];
  links: DraftDocument[];
  onOpenEntity?: (id: string) => void;
}) {
  const currentId = document.id;
  const directTargets = links.filter((l) => text(l.source) === currentId).map((l) => text(l.target));

  // 2-Hop Reachable Entities
  const secondHop: { via: string; target: string; targetLabel: string }[] = [];
  for (const intermediate of directTargets) {
    const nextLinks = documents.filter(
      (item) => item.kind === "Link" && text(item.source) === intermediate && text(item.target) !== currentId,
    );
    for (const n of nextLinks) {
      const targetId = text(n.target);
      const doc = documents.find((d) => d.id === targetId && d.kind === "ObjectType");
      secondHop.push({
        via: intermediate,
        target: targetId,
        targetLabel: text(doc?.label) || targetId,
      });
    }
  }

  return (
    <div className="ontology-side-panel">
      <SheetHelp
        title="关系"
        body="这里配置实体之间的业务关系。左侧两列表单，右侧说明，和「属性与来源」同一套分栏。"
      />

      <div className="ontology-side-card">
        <div className="ontology-card-title">
          <span>关系拓扑与业务键流转</span>
          <span className="ontology-tag">{links.length} 条关系</span>
        </div>
        {links.length ? (
          <div className="relation-flow-stack">
            {links.map((link) => {
              const identityPairs = array(link.identity) as Record<string, unknown>[];
              const isSource = text(link.source) === currentId;
              const otherId = isSource ? text(link.target) : text(link.source);
              const otherDoc = documents.find((d) => d.id === otherId && d.kind === "ObjectType");
              const otherLabel = text(otherDoc?.label) || otherId;
              const sourceKey = identityPairs.map((pair) => text(pair.source)).filter(Boolean).join(" + ") || "id";
              const targetKey = identityPairs.map((pair) => text(pair.target)).filter(Boolean).join(" + ") || "id";
              const card = text(link.cardinality) || "ONE";

              return (
                <div key={link.id} className="relation-flow-box">
                  <div className="flow-nodes">
                    <span className="flow-node-badge current">
                      {text(document.label) || document.id}
                      <small>🔑 {isSource ? sourceKey : targetKey}</small>
                    </span>
                    <span className="flow-arrow">
                      <span className="flow-card-badge">{card === "ONE" ? "至多一个" : "可能多个"}</span>
                      ➔
                    </span>
                    <span className="flow-node-badge target">
                      {otherLabel}
                      <small>🔑 {isSource ? targetKey : sourceKey}</small>
                    </span>
                  </div>
                  <div className="flow-meta">
                    <code>{link.id}</code>
                    {onOpenEntity ? (
                      <button className="text-link" onClick={() => onOpenEntity(otherId)}>跳转到该实体</button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="ontology-hint">点击左侧「添加关系」，在两个实体间声明业务键对应及严格基数。</p>
        )}
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">基数语义保证 (Cardinality Guarantees)</div>
        <div className="cardinality-explainer">
          <div className="card-item">
            <strong>ONE · 源到目标至多一个</strong>
            <p>
              例如：每笔采购订单对应唯一供应商。点查与 Action 前提按声明业务键做有界查找，不会因基数 ONE
              把多行金额误并成一行。同一 PostgreSQL 来源时，集合分析可按该关联对象的属性分组或筛选；
              不能把已画关系理解成任意一对多或跨源 SUM 已可用。
            </p>
          </div>
          <div className="card-item">
            <strong>MANY · 源到目标可能多个</strong>
            <p>
              例如：每个纳税主体对应多个年度申报单。一对多点查必须带齐身份或期间等绑定；展开列表受预算限制。
              跨实体集合汇总不因声明了 MANY 关系而自动开通。
            </p>
          </div>
        </div>
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">跨实体可达路径 (2-Hop Traversal)</div>
        {secondHop.length ? (
          <ul className="ontology-link-list">
            {secondHop.map((hop, idx) => (
              <li key={idx} className="ontology-link-item">
                <div className="link-meta">
                  <span className="direction-tag hop">2-Hop</span>
                  <strong>{text(document.label) || document.id} ➔ {hop.via.split(".").at(-1)} ➔ {hop.targetLabel}</strong>
                </div>
                {onOpenEntity ? (
                  <button className="text-link" onClick={() => onOpenEntity(hop.target)}>查看目标</button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="ontology-hint">
            {links.length ? "暂无二阶可达路径；已声明的关系可直接联查。" : "配置直接关系后，Runtime 可自动穿透多跳业务图谱。"}
          </p>
        )}
      </div>
    </div>
  );
}

export function RulesSidePanel({
  document,
  documents,
  rules,
}: {
  document: DraftDocument;
  documents: DraftDocument[];
  rules: DraftDocument[];
}) {
  const mappings = documents.filter((item) => item.kind === "Mapping" && item.target === document.id);
  const boundProperties = new Set<string>();
  for (const m of mappings) {
    const phys = object(m.physical);
    const cols = object(phys.propertyColumns);
    const ptrs = object(phys.propertyPointers);
    for (const prop of Object.keys({ ...cols, ...ptrs })) {
      boundProperties.add(prop);
    }
  }

  // Extract all inputs referenced in rules
  const referencedInputs: { name: string; required?: boolean; isBound: boolean }[] = [];
  for (const rule of rules) {
    const inputs = array(rule.inputs);
    for (const inp of inputs) {
      const row = inp as Record<string, unknown>;
      const name = text(row.name) || text(row.metric) || "input";
      if (!referencedInputs.some((i) => i.name === name)) {
        referencedInputs.push({
          name,
          required: Boolean(row.required),
          isBound: boundProperties.has(name) || name.includes("."),
        });
      }
    }
  }

  return (
    <div className="ontology-side-panel">
      <SheetHelp
        title="判断"
        body="判断引用属性或指标。先在「属性与来源」把字段对上，再写判断。"
      />

      <div className="ontology-side-card">
        <div className="ontology-card-title">
          <span>确定性三值逻辑模型 (Three-Valued Logic)</span>
          <span className="ontology-tag">严谨裁决</span>
        </div>
        <p className="ontology-desc">
          SemaLoom 判断引擎不同于传统布尔过滤器。发现数据不代表命题为真，数据缺失绝不能默认为假。
        </p>
        <div className="tristate-list">
          <div className="tristate-item true">
            <span className="tristate-badge">TRUE · 成立</span>
            <p>所需语义事实（Semantic Facts）完整观测且完全满足判定表达式。</p>
          </div>
          <div className="tristate-item false">
            <span className="tristate-badge">FALSE · 不成立</span>
            <p>关键数据完整，但业务事实明确违反了规则条件。</p>
          </div>
          <div className="tristate-item unknown">
            <span className="tristate-badge">UNKNOWN · 无法判断</span>
            <p>关键输入缺失、观测为空或来源超时。系统显式保留未决状态，绝不伪造虚假假定。</p>
          </div>
        </div>
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">
          <span>输入事实与绑定状态</span>
          <span className="ontology-tag">{referencedInputs.length} 项依赖</span>
        </div>
        {referencedInputs.length ? (
          <ul className="ontology-dep-list">
            {referencedInputs.map((dep) => (
              <li key={dep.name} className="ontology-dep-item">
                <span className="dep-name">{dep.name}</span>
                <span className={dep.isBound ? "dep-status ok" : "dep-status warn"}>
                  {dep.isBound ? "✓ 已绑定来源" : "! 待绑定物理列"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="ontology-hint">当前判断未声明具体输入参数，或直接基于派生指标求值。</p>
        )}
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">不可伪造证据链 (Evidence Invariant)</div>
        <p className="ontology-desc">
          每次执行判断时，系统都会冻结不可篡改的证据包（Evidence），包含实际观测的事实数值、规则版本、认知时间（Knowledge Time）与审计节点，确保 AI 结论和审计问询均可精确追溯。
        </p>
      </div>
    </div>
  );
}

export function ActionsSidePanel({
  document,
  documents,
  actions,
  rules,
}: {
  document: DraftDocument;
  documents: DraftDocument[];
  actions: DraftDocument[];
  rules: DraftDocument[];
}) {
  const allPreconditions: string[] = [];
  for (const act of actions) {
    const pre = array(act.preconditions).map(String);
    for (const p of pre) {
      if (!allPreconditions.includes(p)) allPreconditions.push(p);
    }
  }

  return (
    <div className="ontology-side-panel">
      <SheetHelp
        title="操作"
        body="操作会改变业务系统。前提判断在「判断」里配置。"
      />

      <div className="ontology-side-card">
        <div className="ontology-card-title">
          <span>受控操作生命周期 (Action Lifecycle)</span>
          <span className="ontology-tag">4 阶段受控</span>
        </div>
        <div className="action-lifecycle-stepper">
          <div className="action-step">
            <span className="step-num">1</span>
            <div className="step-content">
              <strong>计划 (Plan)</strong>
              <p>锁定目标对象实例与参数包，预估变更影响与资源锁</p>
            </div>
          </div>
          <div className="action-step">
            <span className="step-num">2</span>
            <div className="step-content">
              <strong>审批 (Approval)</strong>
              <p>由具备权限的独立责任主体在线签署审批凭证，禁止越权</p>
            </div>
          </div>
          <div className="action-step">
            <span className="step-num">3</span>
            <div className="step-content">
              <strong>执行 (Execution)</strong>
              <p>独立接入层适配器向物理系统下发，隔离业务定义与物理协议</p>
            </div>
          </div>
          <div className="action-step">
            <span className="step-num">4</span>
            <div className="step-content">
              <strong>对账 (Reconciliation)</strong>
              <p>回读外部事实校验最终一致性，固化审计事件（AuditEvent）</p>
            </div>
          </div>
        </div>
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">
          <span>前置门禁判断 (Precondition Claims)</span>
          <span className="ontology-tag">{allPreconditions.length} 项门禁</span>
        </div>
        {allPreconditions.length ? (
          <ul className="ontology-dep-list">
            {allPreconditions.map((claimId) => {
              const rule = documents.find((r) => r.kind === "Rule" && (r.id === claimId || r.claim === claimId));
              const label = text(rule?.label) || claimId;
              return (
                <li key={claimId} className="ontology-dep-item">
                  <span className="dep-name">{label}</span>
                  <span className="dep-status ok">门禁必须为 TRUE</span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="ontology-hint">
            当前操作尚未配置前置判断门禁。生产环境下强烈建议将关键操作绑定合规判断。
          </p>
        )}
      </div>

      <div className="ontology-side-card">
        <div className="ontology-card-title">幂等与安全准则 (Safety Invariants)</div>
        <p className="ontology-desc">
          Query Provider 坚持严格只读原则。Action 是唯一允许对业务系统产生写副作用的通道，每次调用必须携带唯一幂等键（Idempotency Key），防止网络重试造成重复执行。
        </p>
      </div>
    </div>
  );
}
