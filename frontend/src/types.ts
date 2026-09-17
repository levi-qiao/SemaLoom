export type Counts = {
  objects: number;
  links: number;
  mappings: number;
  sources: number;
  rules: number;
  actions?: number;
};

export type GraphMeta = {
  releaseDigest: string;
  onlineValidation: string;
  packs: { id: string; label: string; version: string }[];
  counts: Counts;
};

export type Node = {
  id: string;
  label: string;
  namespace: string;
  properties: string[];
  metricCount: number;
  ruleCount: number;
  actionCount: number;
  mappingCount: number;
  sourceCount: number;
};

export type Edge = {
  id: string;
  label: string;
  source: string;
  target: string;
  cardinality: string;
  sourceKey: string;
  targetKey: string;
};

export type Mapping = {
  id: string;
  label: string;
  target: string;
  objectType: string;
  sourceId: string;
  provider: string;
  resource: string;
  fieldCount: number;
  fields: { semanticField: string; physicalField: string; role: string }[];
  completeness: string;
  expectedCardinality: string;
  perspective: string | null;
  targetKind: "object" | "metric";
  identityField: string;
  identityFields: string[];
  capabilities: string[];
  requiredBindings: string[];
};

export type Source = {
  id: string;
  label: string;
  sourceId: string;
  provider: string;
  mappingCount: number;
  actionCount: number;
  targets: string[];
  namespaces: string[];
  status: string;
};

export type Inspector = {
  id: string;
  label: string;
  version: string;
  namespace: string;
  identityKeys: string[];
  properties: { id: string; label?: string; valueType: string; required?: boolean; unit?: string }[];
  metrics: {
    id: string;
    label: string;
    valueType: string;
    unit: string;
    perspective: string | null;
    grain?: string[];
  }[];
  mappings: Mapping[];
  rules: { id: string; label: string; claim: string | null }[];
  actions: {
    id: string;
    label: string;
    effect: string;
    preconditions: string[];
    parameters: { name: string; valueType: string; required: boolean }[];
    bindings: { id: string; sourceId: string; provider: string }[];
  }[];
  relations: {
    id: string;
    label: string;
    direction: string;
    target: string;
    targetLabel: string;
    cardinality: string;
  }[];
};

export type DraftDocument = Record<string, unknown> & {
  apiVersion: string;
  kind: string;
  id: string;
  version: string;
  label?: string;
};

export type SourceResource = {
  id: string;
  schema: string | null;
  name: string;
  kind: string;
  columns: { name: string; type: string }[];
  method?: string;
  operationId?: string | null;
  parameters?: { name: string; in?: string }[];
};

export type SourceProfileSummary = {
  sourceId: string;
  label: string;
  provider: string;
};

export type View = "chat" | "graph" | "objects" | "sources" | "release";

export type ReviewChanges = {
  added: string[];
  changed: string[];
  removed: string[];
};

export type DraftReview = {
  draftId: string;
  revision: number;
  baseDigest: string;
  candidateDigest: string;
  documents: DraftDocument[];
  exists: boolean;
  changes: ReviewChanges;
};

export type ReleaseRecord = {
  publicationId: string;
  draftId: string;
  draftRevision: number;
  digest: string;
  environment: string;
  environmentRevision: number;
  publisher: string;
  createdAt: string;
};

export type ReleaseState = {
  environment: string;
  activeDigest: string | null;
  environmentRevision: number;
  releases: ReleaseRecord[];
};

export type DraftRevisionRecord = {
  revision: number;
  candidateDigest: string;
  author: string;
  createdAt: string;
};
