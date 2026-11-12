import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  title: ReactNode;
  onClose: () => void;
  /** While true the dialog cannot be dismissed at all (a request is running). */
  busy?: boolean;
  children: ReactNode;
}

/**
 * A centred dialog: labelled, closes on Escape or a backdrop click, takes focus when it opens and
 * hands it back when it closes. Mount it only while it is open.
 */
export default function Modal({ title, onClose, busy = false, children }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  // Latest props for the key listener, so it is bound once.
  const live = useRef({ onClose, busy });
  live.current = { onClose, busy };

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !live.current.busy) {
        e.stopPropagation();
        live.current.onClose();
      }
      // Keep Tab inside the dialog: aria-modal alone does not stop focus leaving it.
      if (e.key === "Tab" && panel.current) {
        const focusable = panel.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;
        const outside = !panel.current.contains(active) || active === panel.current;
        if (e.shiftKey ? active === first || outside : active === last) {
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, []);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/60" onClick={() => !busy && onClose()} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div
          ref={panel}
          role="dialog"
          aria-modal="true"
          aria-label={typeof title === "string" ? title : undefined}
          tabIndex={-1}
          className="pointer-events-auto bg-gray-900 border border-gray-700 rounded-lg w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl focus:outline-none"
        >
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
            <button
              onClick={onClose}
              disabled={busy}
              aria-label="Close"
              className="text-gray-500 hover:text-gray-300 text-xl leading-none disabled:opacity-40"
            >×</button>
          </div>
          {children}
        </div>
      </div>
    </>
  );
}
