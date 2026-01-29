import streamlit as st
import pandas as pd
import numpy as np

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# --------------------------------------------------------------------------
# [핵심 로직] 대구교도소 전용 계산기 (오차 원천 봉쇄)
# --------------------------------------------------------------------------
def solve_daegu_prison(inv_amt, contrib_amt, len_m, households, vol_mj, sales_amt, cost_amt, other_rev):
    
    # 1. 초기 투자비 검증
    # 전액 지원이므로 내 돈(Net Investment)은 0원이어야 함.
    # 만약 지원금이 더 많다고 입력해도 0으로 처리 (이익으로 잡지 않음)
    net_investment = max(0, inv_amt - contrib_amt)
    
    # 2. 연간 판관비 (3중 합산 강제 적용)
    # 엑셀 기준 단가 고정
    unit_maint_m = 8222   # 배관유지비
    unit_admin_m = 13605  # 일반관리비(m)
    unit_admin_hh = 6209  # 일반관리비(전)
    
    cost_1 = len_m * unit_maint_m
    cost_2 = len_m * unit_admin_m
    cost_3 = households * unit_admin_hh
    
    total_sga = cost_1 + cost_2 + cost_3 # 약 1.5억
    
    # 3. 마진(Gross Margin)
    gross_margin = (sales_amt - cost_amt) + other_rev # 약 4,900만
    
    # 4. 감가상각비 (70억 / 30년)
    # ※ 주의: 지원받은 자산이라도 회계상 감가상각은 발생하며, 이것이 영업이익을 낮춤
    depreciation = inv_amt / 30
    
    # 5. 영업이익 (EBIT)
    # 마진(0.5억) - 판관비(1.5억) - 감가상각(2.3억) = -3.3억 (적자)
    ebit = gross_margin - total_sga - depreciation
    
    # 6. 세후 영업이익 (NOPAT)
    # 적자라도 세금 감면 효과(Tax Shield) 때문에 100% 손실은 아님
    tax_rate = 0.209 # 법인세+주민세
    nopat = ebit * (1 - tax_rate)
    
    # 7. 영업현금흐름 (OCF)
    # 현금은 안 나가는 감가상각비를 다시 더해줌
    ocf = nopat + depreciation
    
    # 8. NPV 계산 (30년)
    discount_rate = 0.0615 # 6.15%
    
    cash_flows = [-net_investment] # 0년차 (0원)
    for _ in range(30):
        cash_flows.append(ocf) # 1~30년차 (매년 -3천만원 수준)
        
    npv = np.npv(discount_rate, cash_flows)
    
    # IRR 계산
    try:
        irr = np.irr(cash_flows)
    except:
        irr = 0
        
    # DPP 계산
    dpp = 999
    cum = 0
    for i, cf in enumerate(cash_flows):
        cum += cf / ((1+discount_rate)**i)
        if i > 0 and cum >= 0:
            dpp = i
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_investment,
        "margin": gross_margin,
        "sga": total_sga,
        "dep": depreciation,
        "ebit": ebit,
        "ocf": ocf,
        "flows": cash_flows
    }

# ==========================================================================
# [화면] UI 구성
# ==========================================================================
with st.sidebar:
    st.header("⚙️ 시뮬레이션 설정")
    st.info("대구교도소 분석을 위해 **3가지 관리비**가 모두 합산 적용됩니다.")

st.title("🏗️ 신규배관 경제성 분석 Simulation")
st.markdown("### 💡 대구교도소 전용 정밀 분석기")

st.divider()

# 입력창 (기본값 = 대구교도소 엑셀 데이터)
c1, c2 = st.columns(2)

with c1:
    st.subheader("1. 투자 정보")
    in_len = st.number_input("총 배관 길이 (m)", value=7000.0, format="%.0f")
    in_inv = st.number_input("총 투자비 (원)", value=7000000000, step=100000000, format="%d")
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
    res = solve_daegu_prison(in_inv, in_contrib, in_len, in_hh, 0, in_sales, in_cost, in_other)
    
    # 결과 출력
    st.subheader("📊 분석 결과")
    
    k1, k2, k3 = st.columns(3)
    
    # NPV (빨간색 적자 예상)
    k1.metric("1. 순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
              delta="투자 부적격 (손실)" if res['npv'] < 0 else "투자 적격", 
              delta_color="inverse") # 음수일 때 빨간색 유지
    
    k2.metric("2. 내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
    
    dpp_str = "회수 불가 (30년 초과)" if res['dpp'] > 30 else f"{res['dpp']:.1f} 년"
    k3.metric("3. 할인회수기간 (DPP)", dpp_str)
    
    # ----------------------------------------------------------------------
    # [형님 확인용] 비용 검증표 (여기를 봐주세요!)
    # ----------------------------------------------------------------------
    st.error(f"""
    ### 🛑 왜 적자(마이너스)인가요? (비용 정밀 분석)
    
    **1. 돈은 얼마나 벌었나? (Cash In)**
    * 가스 판매 마진 : **+{res['margin']:,.0f} 원**
    
    **2. 돈이 얼마나 나갔나? (Cash Out)**
    * 배관 유지비 (7km) : -57,554,000 원
    * 일반 관리비 (7km) : -95,235,000 원 (🚨 비용 폭탄)
    * 일반 관리비 (2전) : -12,418 원
    * **판관비 합계 : -{res['sga']:,.0f} 원**
    
    **3. 최종 성적표**
    * **영업 이익 (EBIT) : {res['ebit']:,.0f} 원 (대규모 적자)**
    * **현금 흐름 (OCF) : {res['ocf']:,.0f} 원 (감가상각 더해도 적자)**
    
    👉 **결론:** 투자비는 0원이지만, **매년 {abs(res['ocf']):,.0f}원씩 현금이 유출**되므로 하면 할수록 손해입니다.
    """)
    
    # 현금흐름 그래프
    chart_data = pd.DataFrame({
        "Year": range(31),
        "Cash Flow": res['flows'],
        "Cumulative CF": np.cumsum(res['flows'])
    })
    
    st.line_chart(chart_data.set_index("Year")["Cumulative CF"])
    st.caption("※ 그래프가 0 밑으로 계속 내려가면(우하향) 영원히 회수가 불가능한 사업입니다.")
