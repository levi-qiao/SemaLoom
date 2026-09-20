import { useEffect, useMemo, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { json } from "@codemirror/lang-json";
import { IconAlert } from "./icons";

import type { DraftDocument } from "./types";

type Props = {
  document: DraftDocument;
  allDocuments: DraftDocument[];
  defaultScope?: "entity" | "closure";
  onChange: (next: DraftDocument) => void;
  onError?: (message: string | null) => void;
};

export function EntityDslEditor({
  document,
  allDocuments,
  defaultScope = "entity",
  onChange,
  onError,
}: Props) {
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [scope, setScope] = useState<"entity" | "closure">(defaultScope);
  const [copied, setCopied] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  // Compute canonical entity JSON
  const entityData = useMemo(() => {
    return {
      apiVersion: document.apiVersion ?? "semaloom/v0.1",
      kind: document.kind,
      id: document.id,
      version: document.version ?? "1.0.0",
      label: document.label,
      description: document.description,
      identityKeys: document.identityKeys ?? [],
      properties: document.properties ?? [],
    };
  }, [document]);

  // Compute closure slice (entity + its mappings, links, rules, actions)
  const closureData = useMemo(() => {
    const mappings = allDocuments.filter(
      (item) => item.kind === "Mapping" && item.target === document.id,
    );
    const links = allDocuments.filter(
      (item) =>
        item.kind === "Link" && (item.source === document.id || item.target === document.id),
    );
    const metricIds = new Set(
      allDocuments
        .filter((item) => item.kind === "Metric" && item.objectType === document.id)
        .map((item) => item.id),
    );
    const rules = allDocuments.filter(
      (item) =>
        item.kind === "Rule" &&
        Array.isArray(item.inputs) &&
        item.inputs.some((input) => {
          const row = input as Record<string, unknown>;
          return (
            row.objectType === document.id ||
            (typeof row.metric === "string" && metricIds.has(row.metric))
          );
        }),
    );
    const actions = allDocuments.filter(
      (item) => item.kind === "Action" && item.targetObject === document.id,
    );

    return {
      entity: entityData,
      mappings,
      links,
      rules,
      actions,
    };
  }, [document, allDocuments, entityData]);

  const sourceJson = useMemo(() => {
    const target = scope === "entity" ? entityData : closureData;
    return JSON.stringify(target, null, 2);
  }, [scope, entityData, closureData]);

  const [editorText, setEditorText] = useState(sourceJson);

  // Keep editor in sync during preview mode
  useEffect(() => {
    if (mode === "preview") {
      setEditorText(sourceJson);
      setParseError(null);
    }
  }, [sourceJson, mode]);

  function handleEditorChange(value: string) {
    setEditorText(value);
    if (mode === "edit") {
      try {
        JSON.parse(value);
        setParseError(null);
      } catch (err) {
        setParseError(err instanceof Error ? err.message : "JSON 格式无效");
      }
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(editorText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  function handleFormat() {
    try {
      const parsed = JSON.parse(editorText);
      const formatted = JSON.stringify(parsed, null, 2);
      setEditorText(formatted);
      setParseError(null);
    } catch {
      // Keep as-is if invalid
    }
  }

  function handleApply() {
    if (scope !== "entity") {
      onError?.("整网闭包模式为组合只读视图，请切换到「实体本体」进行实时写入");
      return;
    }
    try {
      const parsed = JSON.parse(editorText) as Record<string, unknown>;
      if (typeof parsed !== "object" || parsed === null) {
        setParseError("根对象必须是一个 JSON Object");
        return;
      }
      if (parsed.id !== document.id) {
        setParseError(`不能通过直接编辑修改语义 ID（当前: ${document.id}）`);
        return;
      }
      if (parsed.kind !== "ObjectType") {
        setParseError("对象类型 kind 必须是 ObjectType");
        return;
      }
      onChange({
        ...document,
        ...parsed,
        id: document.id,
        kind: "ObjectType",
      });
      setParseError(null);
      setMode("preview");
      onError?.(null);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "JSON 解析失败，请检查语法");
    }
  }

  return (
    <div className="entity-dsl-container">
      <div className="entity-dsl-toolbar">
        <div className="entity-dsl-scope-group">
          <span className="entity-dsl-label">语义 DSL</span>
          <button
            type="button"
            className={`dsl-scope-pill ${scope === "entity" ? "active" : ""}`}
            onClick={() => {
              setScope("entity");
              if (mode === "edit") setMode("preview");
            }}
          >
            实体本体 (JSON)
          </button>
          <button
            type="button"
            className={`dsl-scope-pill ${scope === "closure" ? "active" : ""}`}
            onClick={() => {
              setScope("closure");
              if (mode === "edit") setMode("preview");
            }}
          >
            关联全貌 (DSL)
          </button>
        </div>

        <div className="entity-dsl-actions">
          <button
            type="button"
            className="secondary compact-btn"
            onClick={handleCopy}
            title="复制 JSON"
          >
            {copied ? "已复制" : "复制"}
          </button>

          {scope === "entity" ? (
            mode === "preview" ? (
              <button
                type="button"
                className="secondary compact-btn"
                onClick={() => setMode("edit")}
              >
                编辑 JSON
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="secondary compact-btn"
                  onClick={handleFormat}
                  title="格式化 JSON"
                >
                  格式化
                </button>
                <button
                  type="button"
                  className="secondary compact-btn"
                  onClick={() => {
                    setEditorText(sourceJson);
                    setParseError(null);
                    setMode("preview");
                  }}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="primary compact-btn"
                  disabled={Boolean(parseError)}
                  onClick={handleApply}
                >
                  应用修改
                </button>
              </>
            )
          ) : null}
        </div>
      </div>

      {parseError ? (
        <div className="dsl-error-bar" role="alert">
          <IconAlert size={14} style={{ flexShrink: 0 }} />
          <span>{parseError}</span>
        </div>
      ) : null}

      <div className="entity-dsl-editor-wrapper">
        <CodeMirror
          value={editorText}
          height="100%"
          extensions={[json()]}
          editable={mode === "edit" && scope === "entity"}
          onChange={handleEditorChange}
          basicSetup={{
            lineNumbers: true,
            foldGutter: true,
            highlightActiveLineGutter: true,
            highlightSpecialChars: true,
            history: true,
            drawSelection: true,
            dropCursor: true,
            allowMultipleSelections: false,
            indentOnInput: true,
            syntaxHighlighting: true,
            bracketMatching: true,
            closeBrackets: true,
            autocompletion: true,
            rectangularSelection: false,
            crosshairCursor: false,
            highlightActiveLine: mode === "edit",
            highlightSelectionMatches: true,
            closeBracketsKeymap: true,
            defaultKeymap: true,
            searchKeymap: true,
            historyKeymap: true,
            foldKeymap: true,
            completionKeymap: true,
            lintKeymap: true,
          }}
          className="dsl-codemirror-root"
        />
      </div>

      <div className="entity-dsl-footer">
        <span className="dsl-footer-tip">
          {mode === "edit"
            ? "可直接在此编辑实体的 properties 与 identityKeys，点击「应用修改」写入草稿"
            : scope === "entity"
              ? "实时呈现当前实体的规范化本体定义，左侧表单变更实时同步"
              : "包含当前实体及其关联的所有 Mapping、Link、Rule 与 Action 闭包"}
        </span>
        <span className="dsl-mode-badge">{mode === "edit" ? "编辑中" : "只读预览"}</span>
      </div>
    </div>
  );
}
