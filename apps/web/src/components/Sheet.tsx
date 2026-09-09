import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

/**
 * The element a sheet mounts into: the device frame, not the scrolling page.
 * `.sheet` is absolutely positioned, so mounting it inside the scroll
 * container would park it at the bottom of the content instead of the screen.
 */
export const SheetHostContext = createContext<RefObject<HTMLDivElement | null> | null>(null);

/**
 * Anything fixed to the device frame rather than to the page under it — the
 * Butler composer, for one. Absolutely positioned inside `.viewport` it would
 * resolve against the scroll content and paint inside the page's stacking
 * context, which puts it under the nav bar and out of reach.
 */
export function OnScreen({ children }: { children: ReactNode }) {
  const host = useContext(SheetHostContext);
  // The host ref is only filled after the frame has mounted, so the first
  // render has nowhere to send this; the effect brings it back one tick later.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  if (!host) return <>{children}</>;
  if (!ready || !host.current) return null;
  return createPortal(children, host.current);
}

type SheetProps = {
  label: string;
  onClose: () => void;
  children: ReactNode;
};

/** A bottom sheet over the device frame. Escape and the scrim both dismiss it. */
export function Sheet({ label, onClose, children }: SheetProps) {
  const host = useContext(SheetHostContext);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const sheet = (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </>
  );

  return host?.current ? createPortal(sheet, host.current) : sheet;
}
