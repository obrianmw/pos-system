// Every kind of scanner ends up here:
//  - USB / Bluetooth scanners in keyboard mode (most 1D and 2D scanners): they "type" fast and end with
//    Enter or Tab (or nothing). useScannerInput catches those bursts anywhere on the page.
//  - Serial / virtual-COM scanners: connectSerialScanner (Chrome/Edge Web Serial).
//  - Phone/tablet/webcam cameras: ScannerModal in Scanner.tsx.
// normalizeCode cleans what scanners add (AIM prefixes, GS1 data, links in QR codes) and codeKey makes
// EAN-13 / UPC-A / GTIN-14 forms of the same number match.
import { useEffect, useRef } from "react";

/** Clean up a raw scan: AIM symbology prefix (]E0, ]Q1…), GS1 element strings, URLs in QR codes. */
export function normalizeCode(raw: string): string {
  let s = (raw || "").replace(/[\r\n\t]+/g, "").trim();
  s = s.replace(/^\][A-Za-z][0-9A-Za-z]/, ""); // AIM identifier
  s = s.replace(/^\u001d+/, "");
  // GS1: (01)05012345678900(17)... or 0105012345678900... -> the GTIN
  const gs1 = s.match(/^\(01\)(\d{14})/) || s.match(/^01(\d{14})(?:\u001d|\d{2,}|$)/);
  if (gs1) return gs1[1];
  // GS1 Digital Link / our own links: https://x/01/<gtin>/... or ...?code=XYZ
  if (/^https?:\/\//i.test(s)) {
    try {
      const u = new URL(s);
      const dl = u.pathname.match(/\/01\/(\d{8,14})/);
      if (dl) return dl[1];
      const q = u.searchParams.get("code") || u.searchParams.get("c") || u.searchParams.get("sku");
      if (q) return q.trim();
      const hash = u.hash.match(/code=([^&]+)/);
      if (hash) return decodeURIComponent(hash[1]);
    } catch { /* not a URL after all */ }
  }
  return s;
}

/** Same key for the same product number in any length: 012345678905 (UPC-A) = 0012345678905 (EAN-13). */
export const codeKey = (code: string) => {
  const c = normalizeCode(code);
  return /^\d+$/.test(c) ? c.replace(/^0+/, "") : c.toLowerCase();
};

/** Does a scanned code identify this product (barcode in any GTIN length, or SKU)? */
export function matchesCode(p: { barcode?: string | null; sku: string }, scanned: string) {
  const k = codeKey(scanned);
  return !!k && ((!!p.barcode && codeKey(p.barcode) === k) || p.sku.toLowerCase() === normalizeCode(scanned).toLowerCase());
}

const editable = (el: EventTarget | null) => {
  const e = el as HTMLElement | null;
  if (!e) return false;
  return e.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(e.tagName);
};

/** Catch keyboard-mode scanners anywhere on the page (except while a text field has focus, where the
 *  field gets the code as typed text). A scan = 4+ characters arriving < 50 ms apart, ended by Enter,
 *  Tab, or a short pause (scanners set to send no suffix). */
export function useScannerInput(onScan: (code: string) => void, enabled = true) {
  const cb = useRef(onScan); cb.current = onScan;
  useEffect(() => {
    if (!enabled) return;
    let buf = "", last = 0, timer = 0;
    const flush = () => {
      window.clearTimeout(timer);
      const code = normalizeCode(buf);
      buf = "";
      if (code.length >= 4) cb.current(code);
    };
    const onKey = (e: KeyboardEvent) => {
      if (editable(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
      const now = performance.now();
      const quick = now - last < 50;
      last = now;
      if ((e.key === "Enter" || e.key === "Tab") && buf.length >= 4 && quick) {
        e.preventDefault(); flush(); return;
      }
      if (e.key.length !== 1) return;
      if (!quick) buf = "";
      buf += e.key;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { if (buf.length >= 6) flush(); else buf = ""; }, 80);
    };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); window.clearTimeout(timer); };
  }, [enabled]);
}

// ----------------------------------------------------------------------------- serial (COM) scanners
export const serialSupported = () => typeof navigator !== "undefined" && "serial" in navigator;

/** Read codes from a serial scanner, one per line. `pick` asks the user to choose a port (needs a click);
 *  otherwise it reconnects to a port allowed before. Returns a stop function, or null if none. */
export async function connectSerialScanner(onScan: (code: string) => void, pick: boolean, baudRate = 9600) {
  if (!serialSupported()) return null;
  const serial = (navigator as any).serial;
  const port = pick ? await serial.requestPort() : (await serial.getPorts())[0];
  if (!port) return null;
  if (!port.readable) await port.open({ baudRate });
  let stop = false;
  let reader: any;
  (async () => {
    const dec = new TextDecoder();
    let buf = "";
    while (!stop && port.readable) {
      reader = port.readable.getReader();
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done || stop) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split(/\r\n|\r|\n/);
          buf = parts.pop() || "";
          parts.map(normalizeCode).filter((c) => c.length >= 3).forEach(onScan);
        }
      } catch { /* unplugged */ break; } finally { reader.releaseLock(); }
    }
  })();
  return async () => { stop = true; try { await reader?.cancel(); await port.close(); } catch { /* already closed */ } };
}
