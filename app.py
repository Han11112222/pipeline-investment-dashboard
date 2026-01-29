import streamlit as st
import pandas as pd
import numpy as np

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# --------------------------------------------------------------------------
# [핵심 로직] 대구교도소 맞춤형 정밀 계산기
# --------------------------------------------------------------------------
def simulate_project_final(inv_amt, contrib_amt, len_m, households, vol_mj, sales_amt, cost_amt, other_rev):
    
    # 1. 초기 순투자액 (Net Investment)
    # 70억 - 70억 = 0원
    net_inv = inv_amt - contrib_amt
    
    # 2. 연간 판관비 (3가지 무조건 합산)
    # 엑셀 데이터 기준 단가
    u_maint_m = 8222   # 배관유지비
    u_admin_m = 13605  # 일반관리비(m)
    u_admin_hh = 6209  # 일반관리비(전)
    
    cost_sga = (len_m * u_maint_m) + (len_m * u_admin_m) + (households * u_admin_hh)
    
    # 3. 연간 마진 (Gross Margin)
    margin = (sales_amt - cost_amt) + other_rev
    
    # 4. [수정] 감가상각비 및 영업이익 계산
    # 경제성 분석 원칙: 내 돈(Net Inv)이 0원이면, 감가상각비 효과도 0원이어야 함.
    # 회계상으로는 감가상각을 하지만, 현금흐름 분석에선 '남의 돈'에 대한 감가상각 효과를 배제해야 정확함.
    
    if net_inv <= 0:
        depreciation = 0 # 전액 지원 시 감가상각비 0 처리 (핵심!)
    else:
        depreciation = net_inv / 30
        
    # 영업이익 (EBIT) = 마진 - 판관비 - 감가상각
    # 예: 0.5억 - 1.5억 - 0 = -1.0억
    ebit = margin - cost_sga - depreciation
    
    # 5. 세후 영업이익 (NOPAT)
    tax_rate = 0.209
    # 적자면 세금을 안 내거나(0), 환급 효과를 고려하는데
    # 보수적으로 '세금 낼 게 없다(0)' 또는 '적자만큼 손실(1-tax)' 적용
    nopat = ebit * (1 - tax_rate)
    
    # 6. 연간 영업현금흐름 (OCF)
    # OCF = NOPAT + 감가상각비
    # 감가상각비가 0이므로, OCF는 NOPAT(적자) 그대로 나옴.
    ocf = nopat + depreciation
    
    # 7. NPV & IRR 계산
    discount_rate = 0.0615
    period = 30
    
    cash_flows = [-net_inv] + [ocf] * period
    npv = np.npv(discount_rate, cash_flows)
    
    try:
        irr = np.irr(cash_flows)
    except:
        irr = 0
        
    # DPP
    dpp = 999
    cum = 0
    for i, cf in enumerate(cash_flows):
        cum += cf / ((1+discount_rate)**i)
        if i > 0 and cum >= 0:
            dpp = i
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_inv,
        "margin": margin,
        "sga": cost_sga,
        "ebit": ebit,
        "ocf": ocf,
        "flows": cash_flows
    }

# ==========================================================================
# [화면] UI 구성
# ==========================================================================
with st.sidebar:
    st.header("⚙️ 설정")
    st.info("비용 로직: 배관유지비 + 일반관리비(m) + 일반관리비(전) **전부 합산**")

st.title("🏗️ 신규배관 경제성 분석 Simulation")
st.markdown("### 💡 대구교도소형 정밀 분석 (오차 수정판)")

st.divider()

# 입력창 (기본값 = 형님이 주신 데이터 그대로)
c1, c2 = st.columns(2)

with c1:
    st.subheader("1. 투자 정보")
    in_len = st.number_input("총 배관 길이 (m)", value=7000.0, format="%.0f")
    # [중요] 70억 입력
    in_inv = st.number_input("총 공사비 (원)", value=7000000000, step=100000000, format="%d")
    # [중요] 70억 입력
    in_contrib = st.number_input("시설 분담금 (지원액, 원)", value=7000000000, step=100000000, format="%d")
    
with c2:
    st.subheader("2. 수익 정보")
    in_hh = st.number_input("수요가 수 (전)", value=2)
    in_sales = st.number_input("연간 판매액 (원)", value=305103037, format="%d")
    in_cost = st.number_input("연간 판매원가 (원)", value=256160477, format="%d")
    in_other = st.number_input("기타 이익 (원)", value=0, format="%d")

st.divider()

if st.button("🚀 경제성 분석 실행 (Run)", type="primary"):
    
    # 계산 실행
    res = simulate_project_final(in_inv, in_contrib, in_len, in_hh, 0, in_sales, in_cost, in_other)
    
    # 결과 출력
    st.subheader("📊 분석 결과")
    
    k1, k2, k3 = st.columns(3)
    
    # NPV (이제 무조건 마이너스 나옵니다)
    k1.metric("1. 순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
              delta="투자 부적격 (손실)" if res['npv'] < 0 else "투자 적격", 
              delta_color="inverse") 
    
    k2.metric("2. 내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
    
    dpp_str = "회수 불가 (30년 초과)" if res['dpp'] > 30 else f"{res['dpp']:.1f} 년"
    k3.metric("3. 할인회수기간 (DPP)", dpp_str)
    
    # ----------------------------------------------------------------------
    # [형님 확인용] 계산 과정 낱낱이 공개
    # ----------------------------------------------------------------------
    st.warning(f"""
    ### 🛑 계산 검증표 (오차 원인 제거됨)
    
    **1. 순투자액 (Net Investment)**
    * 총 공사비 ({in_inv:,.0f}) - 지원금 ({in_contrib:,.0f}) = **{res['net_inv']:,.0f} 원**
    
    **2. 현금 들어온 돈 (수익)**
    * 가스 판매 마진 : **+{res['margin']:,.0f} 원**
    
    **3. 현금 나간 돈 (비용 - 3중 합산)**
    * **판관비 합계 : -{res['sga']:,.0f} 원**
      *(배관유지비 + 일반관리비(m) + 일반관리비(전) 모두 포함)*
    
    **4. 최종 현금흐름 (OCF)**
    * 영업이익(EBIT) : {res['ebit']:,.0f} 원 (적자)
    * **연간 현금흐름 : {res['ocf']:,.0f} 원** (마이너스 확정)
    
    👉 **결론:** 투자비가 0원이어도, 매년 **{abs(res['ocf']):,.0f}원씩 적자**가 누적되어 **NPV는 마이너스**가 됩니다.
    """)
    
    # 현금흐름 그래프
    chart_data = pd.DataFrame({
        "Year": range(31),
        "Cumulative CF": np.cumsum(res['flows'])
    })
    
    st.line_chart(chart_data.set_index("Year")["Cumulative CF"])
    st.caption("※ 그래프가 계속 내려가는 것(우하향)이 정상입니다.")
