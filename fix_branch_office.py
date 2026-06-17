"""기존 공사현장 데이터에 사업소(branch_office) 자동 매핑 스크립트"""
import sqlite3
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def detect_branch_office(name: str, address: str) -> str:
    combined = (name or '') + ' ' + (address or '')

    # 1순위: 이름/주소에 명시적 지사/관내 언급
    explicit_patterns = [
        (r'합천(관내|지사)', '합천지사'),
        (r'진주(관내|지사|전력)', '진주지사'),
        (r'진해(지사|관내)', '진해지사'),
        (r'남해(지사|관내)', '남해지사'),
        (r'함양(관내|지사)', '함양지사'),
        (r'의령(지사|관내)', '의령지사'),
        (r'하동(관내|지사)', '하동지사'),
        (r'고성(관내|지사)', '고성지사'),
        (r'통영(전력|지사)', '통영지사'),
        (r'밀양(지사|관내)', '밀양지사'),
        (r'창녕(지사|관내)', '창녕지사'),
        (r'산청(지사|관내)', '산청지사'),
        (r'거제(지사|관내)', '거제지사'),
        (r'직할(관내)?', '직할'),
    ]

    for pattern, branch in explicit_patterns:
        if re.search(pattern, combined):
            # "진해구" 주소인데 이름에 "통영전력지사" 같은 경우 → 주소 우선
            pass  # 아래 주소 기반으로 덮어씀

    # 이름에서 명시적 관내/지사 매칭 (이름이 더 정확한 경우가 많음)
    name_only = name or ''
    for pattern, branch in explicit_patterns:
        if re.search(pattern, name_only):
            return branch

    # 주소에서 명시적 관내/지사 매칭
    addr_only = address or ''
    for pattern, branch in explicit_patterns:
        if re.search(pattern, addr_only):
            return branch

    # 2순위: 주소의 시/군 기반 매핑
    addr_city_map = [
        (r'창원시\s*진해구', '진해지사'),
        (r'합천군', '합천지사'),
        (r'진주시', '진주지사'),
        (r'남해군', '남해지사'),
        (r'함양군', '함양지사'),
        (r'의령군', '의령지사'),
        (r'하동군', '하동지사'),
        (r'고성군', '고성지사'),
        (r'통영시', '통영지사'),
        (r'밀양시', '밀양지사'),
        (r'창녕군', '창녕지사'),
        (r'산청군', '산청지사'),
        (r'거제시', '거제지사'),
        (r'사천시', '사천지사'),
        (r'함안군', '함안지사'),
        (r'김해시', '김해지사'),
        (r'양산시', '양산지사'),
        # 창원시 나머지 구는 직할
        (r'창원시', '직할'),
    ]

    for pattern, branch in addr_city_map:
        if re.search(pattern, addr_only):
            return branch

    # 3순위: 이름에서 시/군 힌트
    for pattern, branch in addr_city_map:
        if re.search(pattern, name_only):
            return branch

    # 4순위: "경남본부" 키워드가 이름에 있으면 직할
    if '경남본부' in name_only:
        return '직할'

    return ''


conn = sqlite3.connect('safety_mgr.db')
c = conn.cursor()
c.execute('SELECT id, name, address, branch_office FROM work_sites WHERE is_active=1')
rows = c.fetchall()

updates = []
unmatched = []

for row in rows:
    site_id, name, address, current_bo = row
    detected = detect_branch_office(name, address)
    if detected:
        updates.append((detected, site_id, name, address))
    else:
        unmatched.append((site_id, name, address))

print(f"=== 총 {len(rows)}개 현장 중 {len(updates)}개 매핑 성공, {len(unmatched)}개 미매핑 ===\n")

# 사업소별 카운트
from collections import Counter
branch_counts = Counter(u[0] for u in updates)
print("[ 사업소별 공사 수 ]")
for branch, count in sorted(branch_counts.items(), key=lambda x: -x[1]):
    print(f"  {branch}: {count}건")

if unmatched:
    print(f"\n[ 매핑 실패 {len(unmatched)}건 ]")
    for uid, uname, uaddr in unmatched:
        print(f"  ID {uid}: {uname} | {uaddr}")

# 실제 업데이트
print("\n--- DB 업데이트 적용 중 ---")
for branch, site_id, name, addr in updates:
    c.execute('UPDATE work_sites SET branch_office = ? WHERE id = ?', (branch, site_id))
conn.commit()
print(f"✓ {len(updates)}건 업데이트 완료")

# 미매핑 건도 직할로 기본값
if unmatched:
    for uid, uname, uaddr in unmatched:
        c.execute('UPDATE work_sites SET branch_office = ? WHERE id = ?', ('직할', uid))
    conn.commit()
    print(f"✓ 미매핑 {len(unmatched)}건은 '직할'로 기본 설정")

conn.close()
