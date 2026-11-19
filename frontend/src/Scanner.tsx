// Camera scanning (barcodes + QR) and QR images. USB/Bluetooth scanners don't need this: they type
// the code and press Enter. Cameras only work on https:// or http://localhost (a "secure context").
import { useEffect, useRef, useState } from "react";
import { Camera, CameraOff, ScanLine, X } from "lucide-react";
import QRCode from "qrcode";
import { normalizeCode } from "./scanning";

export const cameraAvailable = () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
export const secureOk = () => typeof window !== "undefined" && window.isSecureContext;

/** Full-screen camera scanner. Calls onCode once per distinct code (with a short cool-down so a
 *  code held in view isn't added ten times). `keepOpen` keeps scanning after each hit (stock counts). */
export function ScannerModal({ title = "Scan a barcode or QR code", keepOpen = false, onCode, onClose, footer }: {
  title?: string; keepOpen?: boolean; onCode: (code: string) => void; onClose: () => void; footer?: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [last, setLast] = useState("");
  const [manual, setManual] = useState("");
  const cb = useRef(onCode); cb.current = onCode;
  const boxId = useRef(`scan-${Math.random().toString(36).slice(2, 8)}`).current;

  useEffect(() => {
    if (!secureOk()) { setError("The camera needs a secure (https) address. Use the https link from the server controller, or type the code below."); return; }
    if (!cameraAvailable()) { setError("This device has no camera the browser can use. Type the code below."); return; }
    let stopped = false;
    let scanner: any;
    const recent = new Map<string, number>();
    (async () => {
      const { Html5Qrcode, Html5QrcodeSupportedFormats: F } = await import("html5-qrcode");
      if (stopped || !box.current) return;
      scanner = new Html5Qrcode(box.current.id, { verbose: false, formatsToSupport: [
        F.QR_CODE, F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF, F.DATA_MATRIX] });
      try {
        await scanner.start({ facingMode: "environment" }, { fps: 12, qrbox: (w: number, h: number) => {
          const s = Math.floor(Math.min(w, h) * 0.75); return { width: Math.min(w * 0.9, s * 1.4), height: s }; } },
          (text: string) => {
            const now = Date.now();
            if ((recent.get(text) || 0) > now - 2000) return;
            recent.set(text, now);
            navigator.vibrate?.(60);
            setLast(text);
            cb.current(normalizeCode(text));
            if (!keepOpen) { stopped = true; scanner.stop().catch(() => {}).finally(onClose); }
          }, () => {});
      } catch (e: any) {
        setError(/permission|denied|NotAllowed/i.test(String(e)) ? "Camera permission was refused. Allow the camera for this site, or type the code below."
          : "Couldn't start the camera. Type the code below.");
      }
    })();
    return () => { stopped = true; scanner?.isScanning && scanner.stop().catch(() => {}); };
  }, []);

  function submitManual(e: React.FormEvent) {
    e.preventDefault();
    if (!manual.trim()) return;
    cb.current(manual.trim()); setLast(manual.trim()); setManual("");
    if (!keepOpen) onClose();
  }

  return (
    <div className="modal scanner-modal" role="dialog" aria-label={title} onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <div className="card scanner-card">
        <div className="inline" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}><ScanLine size={18} style={{ verticalAlign: -3 }} /> {title}</h3>
          <button className="ghost-btn" aria-label="Close scanner" onClick={onClose}><X size={18} /></button>
        </div>
        {error ? <p className="scanner-error"><CameraOff size={18} /> {error}</p>
          : <div id={boxId} ref={box} className="scanner-view" />}
        {last && <p className="muted" style={{ margin: 0 }}>Last scanned: <b>{last}</b></p>}
        <form className="inline" onSubmit={submitManual}>
          <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="…or type a barcode / SKU" aria-label="Barcode or SKU" />
          <button type="submit">Go</button>
        </form>
        {footer}
      </div>
    </div>
  );
}

export function ScanButton({ onClick, label = "Scan" }: { onClick: () => void; label?: string }) {
  return <button type="button" className="scan-btn" onClick={onClick} title="Scan with the camera"><Camera size={18} />{label}</button>;
}

/** A QR code drawn into an <img>. */
export function QrImage({ text, size = 220, label }: { text: string; size?: number; label?: string }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    QRCode.toDataURL(text, { width: size * 2, margin: 1, errorCorrectionLevel: "M" }).then(setSrc).catch(() => setSrc(""));
  }, [text, size]);
  return src ? <img src={src} width={size} height={size} alt={label || `QR code: ${text}`} className="qr-img" /> : <div style={{ width: size, height: size }} className="skeleton" />;
}

export const qrDataUrl = (text: string, width = 300) => QRCode.toDataURL(text, { width, margin: 1 });
