import { useEffect, useRef } from "react";
import { IconClose } from "./icons";

export type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  ariaLabel?: string;
  headerExtra?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  className?: string;
  bodyClassName?: string;
};

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  badge,
  size = "md",
  ariaLabel,
  headerExtra,
  footer,
  children,
  closeOnBackdrop = true,
  closeOnEscape = true,
  className = "",
  bodyClassName = "",
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (closeOnEscape && event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, closeOnEscape, onClose]);

  if (!open) return null;

  const accessibleName = ariaLabel ?? (typeof title === "string" ? title : undefined);

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={accessibleName}
      onClick={(event) => {
        if (closeOnBackdrop && event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        className={`modal-dialog modal-size-${size} ${className}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title-group">
            {badge ? <div className="modal-badge-wrapper">{badge}</div> : null}
            <div className="modal-title-texts">
              <h3 className="modal-title">{title}</h3>
              {subtitle ? <div className="modal-subtitle">{subtitle}</div> : null}
            </div>
          </div>
          <div className="modal-header-actions">
            {headerExtra}
            <button
              type="button"
              className="modal-close-btn"
              onClick={onClose}
              aria-label="关闭"
              title="关闭 (Esc)"
            >
              <IconClose size={14} />
            </button>
          </div>
        </div>

        <div className={`modal-body ${bodyClassName}`}>{children}</div>

        {footer ? <div className="modal-footer">{footer}</div> : null}
      </div>
    </div>
  );
}
