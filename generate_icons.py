"""
PWA 아이콘 생성 스크립트
외부 라이브러리 없이 SVG → PNG 변환 없이 SVG 기반 아이콘 생성

사용법:
    python generate_icons.py
"""

import os

ICON_DIR = os.path.join("frontend", "icons")
os.makedirs(ICON_DIR, exist_ok=True)

# SVG 아이콘 (KEPCO 안전 테마 - 방패 + 온도계)
SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1a5276"/>
      <stop offset="100%" style="stop-color:#2980b9"/>
    </linearGradient>
  </defs>
  <!-- 배경 -->
  <rect width="512" height="512" rx="80" fill="url(#bg)"/>
  <!-- 방패 -->
  <path d="M256 80 L400 140 L400 280 Q400 400 256 450 Q112 400 112 280 L112 140 Z"
        fill="none" stroke="white" stroke-width="16" opacity="0.9"/>
  <!-- 온도계 몸체 -->
  <rect x="232" y="160" width="48" height="160" rx="24" fill="white" opacity="0.9"/>
  <!-- 온도계 구 -->
  <circle cx="256" cy="340" r="36" fill="#e74c3c"/>
  <!-- 온도 수은 -->
  <rect x="244" y="220" width="24" height="120" rx="12" fill="#e74c3c"/>
  <!-- 눈금 -->
  <rect x="282" y="180" width="20" height="4" rx="2" fill="white" opacity="0.6"/>
  <rect x="282" y="200" width="14" height="4" rx="2" fill="white" opacity="0.6"/>
  <rect x="282" y="220" width="20" height="4" rx="2" fill="white" opacity="0.6"/>
  <rect x="282" y="240" width="14" height="4" rx="2" fill="white" opacity="0.6"/>
  <rect x="282" y="260" width="20" height="4" rx="2" fill="white" opacity="0.6"/>
</svg>"""

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

for size in SIZES:
    svg_content = SVG_TEMPLATE.format(size=size)
    filepath = os.path.join(ICON_DIR, f"icon-{size}.svg")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(svg_content)
    print(f"  생성: {filepath}")

# badge 아이콘 (작은 알림용)
BADGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72">
  <circle cx="36" cy="36" r="32" fill="#e74c3c"/>
  <text x="36" y="44" text-anchor="middle" fill="white"
        font-family="Arial" font-size="28" font-weight="bold">!</text>
</svg>"""

badge_path = os.path.join(ICON_DIR, "badge-72.svg")
with open(badge_path, "w", encoding="utf-8") as f:
    f.write(BADGE_SVG)
print(f"  생성: {badge_path}")

print()
print(f"아이콘 {len(SIZES) + 1}개 생성 완료! ({ICON_DIR}/)")
print()
print("참고: SVG 아이콘은 대부분의 브라우저에서 PWA 아이콘으로 사용 가능합니다.")
print("PNG가 필요한 경우 아래 사이트에서 SVG → PNG 변환할 수 있습니다:")
print("  https://svgtopng.com/")
