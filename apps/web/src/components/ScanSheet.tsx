import { useEffect, useRef, useState } from "react";

import type { Capture } from "@kira/contracts";

import { useCreateDraft, useReadCapture } from "../api/hooks";
import { IcArrow, IcCam } from "./Icons";
import { Sheet } from "./Sheet";

type ScanSheetProps = {
  onClose: () => void;
  onAsk: (text: string, attachment: Capture & { preview?: string }) => void;
  /** Runs the camera prototype locally, without uploading a placeholder file. */
  demo?: boolean;
};

const DEMO_RECEIPT: Capture = {
  kind: "receipt",
  is_transaction: true,
  source: "receipt",
  merchant: "Nasi Kandar Pelita",
  amount_sen: 1890,
  occurred_on: "2026-09-03",
  category: "food",
  confidence: 94,
  note: "Line item total matched, tax line ignored.",
  transcript: "",
  fields: [
    { label: "Merchant", value: "Nasi Kandar Pelita", confidence: 94 },
    { label: "Total", value: "RM18.90", confidence: 94 },
    { label: "Date", value: "3 Sep 2026", confidence: 94 },
    { label: "Category", value: "Food & drink", confidence: 83 },
  ],
};

/**
 * Point the camera at a receipt.
 *
 * `capture="environment"` opens the rear camera on a phone and falls back to
 * the file picker everywhere else, so the same control works on the desk and
 * in the queue. The bytes go to the reader; what comes back is a proposal
 * with a confidence on every field, and it stays a proposal until confirmed.
 */
export function ScanSheet({ onClose, onAsk, demo = false }: ScanSheetProps) {
  return (
    <Sheet label="Scan a receipt" onClose={onClose}>
      <div className="grab" />
      <ScanBody onClose={onClose} onAsk={onAsk} demo={demo} />
    </Sheet>
  );
}

/** The reading itself, so the entry sheet can host it beside the other ways in. */
export function ScanBody({ onClose, onAsk, demo = false }: ScanSheetProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const demoTimer = useRef<number | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [demoResult, setDemoResult] = useState<Capture | null>(null);
  const [demoStage, setDemoStage] = useState<"aiming" | "reading">("aiming");
  const read = useReadCapture("receipt");
  const draft = useCreateDraft();
  const result = demoResult ?? (demo ? undefined : read.data);
  const canSave = Boolean(
    result?.is_transaction && result.merchant && result.amount_sen !== null,
  );

  useEffect(() => () => {
    if (demoTimer.current !== null) window.clearTimeout(demoTimer.current);
  }, []);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setDemoResult(null);
    setPreview(URL.createObjectURL(file));
    read.mutate(file);
  };

  const startDemoRead = () => {
    setDemoStage("reading");
    demoTimer.current = window.setTimeout(() => {
      setDemoResult(DEMO_RECEIPT);
      demoTimer.current = null;
    }, 650);
  };

  const resetDemo = () => {
    if (demoTimer.current !== null) window.clearTimeout(demoTimer.current);
    demoTimer.current = null;
    setDemoResult(null);
    setDemoStage("aiming");
  };

  return (
    <>
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            {result ? "What I read" : demo ? "Camera" : "Receipt"}
          </p>
          <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
            {result ? "Check it before I use it" : demo ? "Scan the receipt" : "Show me the receipt"}
          </h2>
        </div>
      </div>

      {demo && !result && (
        <>
          <div className="scanframe demo-camera" aria-label="Receipt camera preview">
            <div className="receipt" aria-hidden="true">
              <strong>PELITA</strong><hr />
              <div className="r-row"><span>Nasi kandar</span><span>18.90</span></div>
              <div className="r-row r-tot"><span>TOTAL</span><span>RM18.90</span></div>
            </div>
            <span className="scan-guide" />
            {demoStage === "reading" && <span className="laser" />}
          </div>
          {demoStage === "reading" ? (
            <div className="capture-status" role="status">
              <span className="thinking"><i /><i /><i /></span>
              Reading the receipt…
            </div>
          ) : (
            <div style={{ display: "flex", gap: 9, marginTop: 16 }}>
              <button className="btn btn-sm btn-ghost" style={{ flex: 1 }} onClick={onClose}>
                Cancel
              </button>
              <button className="btn btn-accent btn-sm" style={{ flex: 1 }} onClick={startDemoRead}>
                Scan receipt <IcArrow size={14} />
              </button>
            </div>
          )}
          <p className="sheet-note">Preview only. Nothing reaches your ledger until you review it.</p>
        </>
      )}

      {!demo && !result && !read.isPending && (
        <>
          <div className="pick-grid">
            <button className="pick" onClick={() => fileRef.current?.click()}>
              <IcCam size={22} />
              <b>Take a photo</b>
              <span>Camera, or the camera roll.</span>
            </button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            aria-label="Receipt photo"
            onChange={(event) => void onFile(event.target.files?.[0])}
            style={{ display: "none" }}
          />
          <p className="sheet-note">
            The photo goes to the reader and nowhere else. Nothing reaches your ledger until
            you confirm it.
          </p>
        </>
      )}

      {preview && (
        <div className="scanframe">
          <img src={preview} alt="The receipt you chose" />
          {read.isPending && <span className="laser" />}
        </div>
      )}

      {read.isPending && (
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 16 }}>
          <span className="thinking">
            <i />
            <i />
            <i />
          </span>
          <span style={{ fontSize: 13, color: "rgba(233,237,233,.6)" }}>
            Finding the merchant, the total and the date…
          </span>
        </div>
      )}

      {read.isError && <p className="sheet-note">I could not read that one. Try another photo.</p>}

      {result && (
        <>
          <div style={{ marginTop: 16 }}>
            {result.fields.map((field, index) => (
              <div className="field" key={field.label} style={{ animationDelay: `${index * 90}ms` }}>
                <span className="field-l">{field.label}</span>
                <span className="field-v">{field.value}</span>
                <span className="field-c">
                  <i style={{ width: `${field.confidence}%` }} />
                  <span>{field.confidence}%</span>
                </span>
              </div>
            ))}
          </div>
          <p className="sheet-note">{result.note}</p>
          <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
            {demo && (
              <button className="btn btn-sm btn-ghost" onClick={resetDemo}>
                Scan again
              </button>
            )}
            {canSave && (
              <button
                className="btn btn-sm btn-ghost"
                style={{ flex: 1 }}
                disabled={draft.isPending}
                onClick={() =>
                  draft.mutate(
                    {
                      merchant: result.merchant!,
                      amount_sen: result.amount_sen!,
                      occurred_on: result.occurred_on,
                      category: result.category,
                      source: result.source,
                      confidence: result.confidence,
                      note: result.note,
                    },
                    { onSuccess: onClose },
                  )
                }
              >
                Save as draft
              </button>
            )}
            <button
              className="btn btn-accent btn-sm"
              style={{ flex: 1 }}
              onClick={() =>
                onAsk("What does this receipt do to my day?", {
                  ...result,
                  preview: preview ?? undefined,
                })
              }
            >
              Ask Kira <IcArrow size={14} />
            </button>
          </div>
        </>
      )}
    </>
  );
}
