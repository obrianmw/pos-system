// The shop's logo (or a default cart mark) and name, kept in step with the Branding settings.
import { useEffect, useState } from "react";
import { ShoppingCart } from "lucide-react";
import { BrandingSettings, getBranding, onBranding } from "./brand";

export function useBrandingState() {
  const [b, setB] = useState<BrandingSettings | null>(getBranding());
  useEffect(() => onBranding(setB), []);
  return b;
}

export function BrandMark({ size = 36 }: { size?: number }) {
  const b = useBrandingState();
  return b?.logo_url
    ? <img className="brand-logo" src={b.logo_url} alt="" style={{ height: size, maxWidth: size * 3 }} />
    : <span className="logo-mark" style={{ width: size, height: size }}><ShoppingCart size={Math.round(size / 2)} /></span>;
}
