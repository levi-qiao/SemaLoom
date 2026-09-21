import { useEffect, useMemo, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { json } from "@codemirror/lang-json";
import { IconAlert } from "./icons";
import { useI18n } from "./i18n";

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
  const { t } = useI18n();
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
        setParseError(err instanceof Error ? err.message : t("dsl.invalidJson"));
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
      onError?.(t("dsl.readOnlyWarning"));
      return;
    }
    try {
      const parsed = JSON.parse(editorText) as Record<string, unknown>;
      if (typeof parsed !== "object" || parsed === null) {
        setParseError(t("dsl.mustBeObject"));
        return;
      }
      if (parsed.id !== document.id) {
        setParseError(t("dsl.cannotChangeId", { id: document.id }));
        return;
      }
      if (parsed.kind !== "ObjectType") {
        setParseError(t("dsl.kindMustBeObjectType"));
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
      setParseError(err instanceof Error ? err.message : t("dsl.parseError"));
    }
  }

  return (
    <div className="entity-dsl-container">
      <div className="entity-dsl-toolbar">
        <div className="entity-dsl-scope-group">
          <span className="entity-dsl-label">{t("dsl.title")}</span>
          <button
            type="button"
            className={`dsl-scope-pill ${scope === "entity" ? "active" : ""}`}
            onClick={() => {
              setScope("entity");
              if (mode === "edit") setMode("preview");
            }}
          >
            {t("dsl.entityJson")}
          </button>
          <button
            type="button"
            className={`dsl-scope-pill ${scope === "closure" ? "active" : ""}`}
            onClick={() => {
              setScope("closure");
              if (mode === "edit") setMode("preview");
            }}
          >
            {t("dsl.closureDsl")}
          </button>
        </div>

        <div className="entity-dsl-actions">
          <button
            type="button"
            className="secondary compact-btn"
            onClick={handleCopy}
            title={`${t("common.copy")} JSON`}
          >
            {copied ? t("common.copied") : t("common.copy")}
          </button>

          {scope === "entity" ? (
            mode === "preview" ? (
              <button
                type="button"
                className="secondary compact-btn"
                onClick={() => setMode("edit")}
              >
                {t("dsl.editJson")}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="secondary compact-btn"
                  onClick={handleFormat}
                  title={`${t("common.format")} JSON`}
                >
                  {t("common.format")}
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
                  {t("common.cancel")}
                </button>
                <button
                  type="button"
                  className="primary compact-btn"
                  disabled={Boolean(parseError)}
                  onClick={handleApply}
                >
                  {t("dsl.applyChanges")}
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
            ? t("dsl.editHint")
            : scope === "entity"
              ? t("dsl.entityJsonHint")
              : t("dsl.closureHint")}
        </span>
        <span className="dsl-mode-badge">{mode === "edit" ? t("dsl.editingMode") : t("dsl.readonlyMode")}</span>
      </div>
    </div>
  );
}
