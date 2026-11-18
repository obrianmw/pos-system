"""Flat illustrations for the demo catalogue (stand-ins until the shop uploads real product photos).

Each picture is a 400x400 SVG: a soft tinted tile, a ground shadow and the item drawn from simple shapes.
Original artwork made for this project - no third-party images or brands.
"""

TINTS = {  # category family -> (top, bottom) background colors
    "meat": ("#fde8e4", "#f9cfc6"), "veg": ("#e6f6e3", "#cdebc6"), "fruit": ("#fff4d9", "#ffe4a8"),
    "bakery": ("#fbefe0", "#f3dcc0"), "staple": ("#eef1f5", "#dde3eb"), "drink": ("#e3f0fb", "#c9e1f6"),
    "home": ("#f1ebfa", "#e1d5f4"), "service": ("#e6f4f4", "#c9e8e8"),
}


def _tile(family, body, label=""):
    a, b = TINTS[family]
    text = (f'<text x="200" y="372" text-anchor="middle" font-family="Inter,Segoe UI,Arial,sans-serif" '
            f'font-size="26" font-weight="700" fill="#3b3f46" opacity=".55">{label}</text>') if label else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{a}"/>'
            f'<stop offset="1" stop-color="{b}"/></linearGradient></defs>'
            f'<rect width="400" height="400" rx="48" fill="url(#bg)"/>'
            f'<ellipse cx="200" cy="318" rx="120" ry="16" fill="#000" opacity=".08"/>{body}{text}</svg>')


def _sack(color, label):
    return (f'<path d="M120 120 Q130 92 160 100 L240 100 Q270 92 280 120 L296 290 Q298 316 270 318 L130 318 '
            f'Q102 316 104 290 Z" fill="#efe3c8" stroke="#c9b48a" stroke-width="5"/>'
            f'<path d="M150 100 Q200 120 250 100" fill="none" stroke="#c9b48a" stroke-width="5"/>'
            f'<rect x="132" y="170" width="136" height="80" rx="14" fill="{color}"/>'
            f'<text x="200" y="222" text-anchor="middle" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="30" '
            f'font-weight="800" fill="#fff">{label}</text>')


ART = {
    "beef": ("meat", '<path d="M110 200 Q100 130 180 120 Q270 105 300 170 Q320 240 250 280 Q170 320 125 270 Q100 240 110 200Z" fill="#b83a2e"/>'
                     '<path d="M140 190 Q190 160 250 175 M150 235 Q200 215 265 230" stroke="#f3d3c8" stroke-width="10" fill="none" stroke-linecap="round"/>'
                     '<circle cx="235" cy="205" r="20" fill="#f6e2da"/>'),
    "chicken": ("meat", '<ellipse cx="185" cy="200" rx="95" ry="80" fill="#d98b3a" transform="rotate(-25 185 200)"/>'
                        '<ellipse cx="170" cy="185" rx="55" ry="40" fill="#e8a65a" transform="rotate(-25 170 185)"/>'
                        '<rect x="250" y="235" width="60" height="18" rx="9" fill="#f7efe3" transform="rotate(35 280 244)"/>'
                        '<circle cx="305" cy="275" r="17" fill="#f7efe3"/><circle cx="318" cy="258" r="15" fill="#f7efe3"/>'),
    "goat": ("meat", '<rect x="105" y="140" width="190" height="140" rx="36" fill="#a8432f"/>'
                     '<g stroke="#f4ece4" stroke-width="12" stroke-linecap="round"><path d="M140 160 V262"/><path d="M180 156 V266"/>'
                     '<path d="M220 156 V266"/><path d="M260 160 V262"/></g>'),
    "tomato": ("veg", '<circle cx="200" cy="215" r="98" fill="#e2402f"/><circle cx="165" cy="180" r="24" fill="#f17a6c" opacity=".7"/>'
                      '<path d="M200 120 l18 -22 l6 28 l30 -6 l-22 22 l22 16 l-30 2 l-6 26 l-18 -22 l-18 22 l-6 -26 l-30 -2 l22 -16 l-22 -22 l30 6 l6 -28z" fill="#3f9142"/>'),
    "onion": ("veg", '<path d="M200 105 Q220 150 280 190 Q320 260 250 305 Q200 330 150 305 Q80 260 120 190 Q180 150 200 105Z" fill="#b46ca3"/>'
                     '<path d="M200 120 Q185 200 175 300 M200 120 Q215 200 225 300 M200 120 V305" stroke="#e8c3dc" stroke-width="5" fill="none"/>'
                     '<path d="M190 105 Q200 70 214 92" stroke="#6f9a3a" stroke-width="8" fill="none" stroke-linecap="round"/>'),
    "cabbage": ("veg", '<circle cx="200" cy="210" r="105" fill="#7fbf5a"/><circle cx="200" cy="215" r="78" fill="#a6d77c"/>'
                       '<circle cx="200" cy="220" r="48" fill="#cbe9a5"/>'
                       '<path d="M200 120 V300 M120 180 Q200 230 280 180" stroke="#6aa847" stroke-width="5" fill="none"/>'),
    "potato": ("veg", '<ellipse cx="160" cy="225" rx="80" ry="58" fill="#c9965b"/><ellipse cx="245" cy="205" rx="72" ry="54" fill="#d6a76c"/>'
                      '<g fill="#a87a45"><circle cx="140" cy="210" r="5"/><circle cx="180" cy="245" r="5"/><circle cx="235" cy="190" r="5"/>'
                      '<circle cx="268" cy="220" r="5"/><circle cx="150" cy="250" r="4"/></g>'),
    "banana": ("fruit", '<path d="M110 150 Q140 300 300 270 Q320 262 312 248 Q190 255 150 140 Q140 120 120 128 Q104 134 110 150Z" fill="#f5c518"/>'
                        '<path d="M130 150 Q180 260 300 258" stroke="#d9a90f" stroke-width="5" fill="none"/>'
                        '<rect x="104" y="118" width="22" height="22" rx="5" fill="#6b5a2a"/>'),
    "orange": ("fruit", '<circle cx="200" cy="215" r="100" fill="#f39a1e"/><circle cx="168" cy="182" r="24" fill="#f8bd5f" opacity=".75"/>'
                        '<path d="M200 118 Q230 80 270 96 Q240 128 200 118Z" fill="#4f9a3d"/>'),
    "bread": ("bakery", '<path d="M90 230 Q90 140 200 140 Q310 140 310 230 L310 285 Q310 300 295 300 L105 300 Q90 300 90 285Z" fill="#d6964a"/>'
                        '<path d="M100 225 Q100 155 200 155 Q300 155 300 225" fill="#e6b06a"/>'
                        '<path d="M150 175 l20 30 M195 168 l20 30 M240 175 l20 30" stroke="#b9772f" stroke-width="9" stroke-linecap="round"/>'),
    "sugar": ("staple", _sack("#3c7dd9", "SUGAR")),
    "rice": ("staple", _sack("#2e9d6a", "RICE")),
    "maize": ("staple", _sack("#d18b1a", "MAIZE")),
    "oil": ("staple", '<path d="M170 100 h60 v30 q40 25 40 70 v100 q0 20 -20 20 h-100 q-20 0 -20 -20 v-100 q0 -45 40 -70z" fill="#f2c14e"/>'
                      '<rect x="165" y="82" width="70" height="26" rx="8" fill="#2f6f3e"/>'
                      '<rect x="140" y="210" width="120" height="60" rx="10" fill="#fff" opacity=".85"/>'
                      '<text x="200" y="250" text-anchor="middle" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="28" font-weight="800" fill="#b8860b">OIL</text>'),
    "peanut": ("staple", '<rect x="120" y="140" width="160" height="165" rx="26" fill="#b5763a"/>'
                         '<rect x="112" y="112" width="176" height="40" rx="12" fill="#c0392b"/>'
                         '<rect x="138" y="190" width="124" height="70" rx="12" fill="#fff4e0"/>'
                         '<ellipse cx="200" cy="225" rx="34" ry="20" fill="#c8894a"/>'),
    "soap": ("home", '<rect x="105" y="170" width="190" height="110" rx="34" fill="#f39fc0"/>'
                     '<rect x="125" y="185" width="150" height="40" rx="16" fill="#f8c6da"/>'
                     '<g fill="#fff" opacity=".85"><circle cx="150" cy="140" r="18"/><circle cx="190" cy="118" r="12"/><circle cx="235" cy="135" r="22"/></g>'),
    "tissue": ("home", '<rect x="120" y="140" width="160" height="160" rx="18" fill="#fbfbfb" stroke="#d7d9de" stroke-width="5"/>'
                       '<ellipse cx="200" cy="140" rx="80" ry="24" fill="#ffffff" stroke="#d7d9de" stroke-width="5"/>'
                       '<ellipse cx="200" cy="140" rx="22" ry="8" fill="#c9ccd3"/>'),
    "cola": ("drink", '<path d="M178 80 h44 v40 q30 30 30 80 v100 q0 20 -20 20 h-64 q-20 0 -20 -20 v-100 q0 -50 30 -80z" fill="#5a2e1e"/>'
                      '<rect x="174" y="66" width="52" height="20" rx="6" fill="#d23a2e"/>'
                      '<rect x="150" y="200" width="100" height="56" rx="10" fill="#d23a2e"/>'
                      '<text x="200" y="237" text-anchor="middle" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="24" font-weight="800" fill="#fff">COLA</text>'),
    "water": ("drink", '<path d="M178 80 h44 v40 q30 30 30 80 v100 q0 20 -20 20 h-64 q-20 0 -20 -20 v-100 q0 -50 30 -80z" fill="#9fd3f5" opacity=".9"/>'
                       '<rect x="174" y="66" width="52" height="20" rx="6" fill="#2a78d6"/>'
                       '<rect x="150" y="200" width="100" height="56" rx="10" fill="#2a78d6"/>'
                       '<path d="M200 212 q-14 18 0 30 q14 -12 0 -30z" fill="#fff"/>'),
    "airtime": ("service", '<rect x="140" y="90" width="120" height="220" rx="22" fill="#25313f"/>'
                           '<rect x="152" y="112" width="96" height="160" rx="8" fill="#5fc4c4"/>'
                           '<circle cx="200" cy="292" r="8" fill="#5fc4c4"/>'
                           '<path d="M285 150 q22 30 0 60 M305 130 q40 50 0 100" stroke="#25313f" stroke-width="9" fill="none" stroke-linecap="round"/>'),
}


def svg(key):
    family, body = ART[key]
    return _tile(family, body)
