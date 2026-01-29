import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# --------------------------------------------------------------------------
# [핵심 로직] 3중 비용 합산 & 정확한 현금흐름 계산
# --------------------------------------------------------------------------
def simulate_project(inv_amt, contrib_amt, len_m, vol_mj, sales_amt, cost_amt, other_rev, 
                     num_jeon, discount_rate, tax_rate, period,
                     cost_maint, cost_admin_jeon, cost_admin_m):
    
    # 1. 초기 순투자액 (내 돈)
    # 공사비(70억) - 지원금(70억) = 0원
    net_inv = max(0, inv_amt - contrib_amt)
    
    # 2. 판관비 (3가지 무조건 합산)
    # 형님 요청대로 7,000m에 대한 비용을 다 때려 넣습니다.
    cost_1 = len_m * cost_maint        # 배관 유지비
    cost_2 = len_m * cost_admin_m      # 일반 관리비(m당) -> 여기가 큽니다
    cost_3 = num_jeon * cost_admin_jeon  # 일반 관리비(전당)
    
    total_sga = cost_1 + cost_2 + cost_3
    
    # 3. 영업이익 계산
    # 마진(4천만) - 판관비(1.5억) = -1.1억 (적자)
    gross_margin = (sales_amt - cost_amt) + other_rev
    
    # 감가상각: 내 돈(net_inv)이 0원이면 감가상각비도 0원 (세금 효과 제거)
    if net_inv <= 0:
        dep = 0
    else:
        dep = net_inv / period
        
    ebit = gross_margin - total_sga - dep
    
    # 4. 현금흐름 (OCF)
    nopat = ebit * (1 - tax_rate) # 세후 영업이익
    ocf = nopat + dep             # 영업현금흐름 (적자 유지)
    
    # 5. NPV 계산
    cash_flows = [-net_inv] + [ocf] * int(period)
    npv = np.npv(discount_rate, cash_flows)
    
    try:
        irr = np.irr(cash_flows)
    except:
        irr = 0
        
    # DPP
    dpp = 999.0
    cum = 0
    for i, cf in enumerate(cash_flows):
        cum += cf / ((1+discount_rate)**i)
        if i > 0 and cum >= 0:
            dpp = float(i)
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_inv, "ocf": ocf, "ebit": ebit, "sga": total_sga,
        "flows": cash_flows
    }

# ==========================================================================
# [화면 구성]
# ==========================================================================
with st.sidebar:
    st.header("⚙️ 설정")
    st.info("비용 로직: 배관유지비 + 일반관리비(m) + 일반관리비(전) **전부 합산**")

st.title("🏗️ 신규배관 경제성 분석 Simulation")
st.markdown("### 💡 대구교도소형 정밀 분석")
st.warning("⚠️ **주의:** [기타 연간 이익]에 공사비를 넣지 마세요! 그건 매년 버는 돈입니다.")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. 투자 정보")
    sim_len = st.number_input("투자 길이 (m)", value=7000.0)
    sim_inv = st.number_input("총 공사비 (원)", value=7000000000, step=100000000, format="%d")
    
    # [수정] 이름을 명확하게 변경
    sim_contrib = st.number_input("시설 분담금 (공사비 지원액, 원)", value=7000000000, step=100000000, format="%d")
    st.caption("※ 전액 지원이면 총 공사비와 같은 금액을 입력하세요.")
    
    st.markdown("---")
    st.subheader("2. 시설 특성")
    sim_jeon = st.number_input("공급 전수 (전)", value=2)

with col2:
    st.subheader("3. 수익 정보")
    sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)
    sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
    sim_cost = st.number_input("연간 판매원가 (매입비, 원)", value=256160477)
    
    # [🚨 여기가 문제의 그곳!]
    sim_other = st.number_input("기타 연간 이익 (매년 발생, 원)", value=0) 
    st.caption("🚨 **여기에 70억 넣으면 안 됩니다!** (매년 70억 버는 게 됨)")

st.divider()

# 내부 파라미터 (고정)
RATE = 6.15 / 100
TAX = 20.9 / 100
PERIOD = 30
COST_MAINT = 8222
COST_ADMIN_JEON = 6209
COST_ADMIN_M = 13605

if st.button("🚀 경제성 분석 실행 (Run)", type="primary"):
    res = simulate_project(
        sim_inv, sim_contrib, sim_len, sim_vol, sim_rev, sim_cost, sim_other,
        sim_jeon, RATE, TAX, PERIOD,
        COST_MAINT, COST_ADMIN_JEON, COST_ADMIN_M
    )
    
    st.subheader("📊 분석 결과")
    m1, m2, m3 = st.columns(3)
    
    m1.metric("1. 순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
              delta="투자 적격" if res['npv']>0 else "투자 부적격 (손실)", 
              delta_color="normal" if res['npv']>0 else "inverse")
    
    m2.metric("2. 내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
    
    dpp_str = "회수 불가" if res['dpp'] > 30 else f"{res['dpp']:.1f} 년"
    m3.metric("3. 할인회수기간 (DPP)", dpp_str)
    
    st.error(f"""
    **[검산표]**
    * **0년차 내 투자금:** {res['net_inv']:,.0f} 원 (공사비 - 지원금)
    * **연간 판관비 합계:** {res['sga']:,.0f} 원 (여기서 1.5억 나감 🚨)
    * **연간 영업이익:** {res['ebit']:,.0f} 원 (적자 확정)
    """)
    
    cf_df = pd.DataFrame({"Year": range(31), "Cash Flow": res['flows']})
    st.bar_chart(cf_df.set_index("Year"))
