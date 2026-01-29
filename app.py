import streamlit as st
import pandas as pd
import numpy as np
import io

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기 v2.1", layout="wide")

# --------------------------------------------------------------------------
# [함수] 금융 계산
# --------------------------------------------------------------------------
def manual_npv(rate, values):
    total = 0.0
    for i, v in enumerate(values):
        total += v / ((1 + rate) ** i)
    return total

def manual_irr(values):
    if sum(values) <= 0: return 0.0
    try:
        if all(v >= 0 for v in values) or all(v <= 0 for v in values): return 0.0
        rate = 0.1 
        for _ in range(100):
            npv = 0.0
            d_npv = 0.0
            for i, v in enumerate(values):
                term = v / ((1 + rate) ** i)
                npv += term
                d_npv -= i * term / (1 + rate)
            if abs(npv) < 1e-6: return rate
            if d_npv == 0: return 0.0
            rate -= npv / d_npv
            if abs(rate) > 10: return 0.0
        return rate
    except: return 0.0

# --------------------------------------------------------------------------
# [핵심 로직] 시뮬레이션
# --------------------------------------------------------------------------
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_subsidy, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, 
                     c_maint, c_adm_jeon, c_adm_m):
    
    # 1. 초기 순투자액 (Year 0)
    net_inv = sim_inv - sim_contrib - sim_other_subsidy
    
    # 2. 연간 판관비
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    
    # 3. 영업이익 (EBIT)
    margin = sim_rev - sim_cost
    depreciation = sim_inv / period 
    ebit = margin - cost_sga - depreciation
    
    # 4. 연간 현금흐름 (OCF)
    # 영업적자 시 세금 환급 효과는 실무적으로 제외(0) 처리
    tax_amount = max(0, ebit * tax)
    ocf = ebit - tax_amount + depreciation
    
    # 5. 현금흐름 배열
    flows = [-net_inv] + [ocf] * int(period)
    
    # 6. 지표 계산
    npv = manual_npv(rate, flows)
    irr = 0.0 if (npv <= 0 and ocf <= 0) else manual_irr(flows)
    
    # DPP
    dpp = 999.0
    cum = 0.0
    for i, f in enumerate(flows):
        cum += f / ((1 + rate) ** i)
        if i > 0 and cum >= 0:
            dpp = float(i)
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_inv, "ocf": ocf, "ebit": ebit, "sga": cost_sga, 
        "dep": depreciation, "flows": flows
    }

# --------------------------------------------------------------------------
# [UI] 화면 구성
# --------------------------------------------------------------------------
st.title("🏗️ 신규배관 경제성 분석 Simulation")

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. 투자 정보")
    sim_len = st.number_input("투자 길이 (m)", value=7000.0)
    sim_inv = st.number_input("총 공사비 (원)", value=7000000000, step=10000000, format="%d")
    sim_contrib = st.number_input("시설 분담금 (원)", value=22048100, step=1000000, format="%d")
    sim_other = st.number_input("기타 이익 (보조금, 원)", value=7000000000, step=10000000, format="%d")
    sim_jeon = st.number_input("공급 전수 (전)", value=2)

with c2:
    st.subheader("2. 수익 정보 (연간)")
    # 요구사항: 연간 판매량(MJ)을 첫 번째로 이동
    sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)
    sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
    sim_cost = st.number_input("연간 판매원가 (원)", value=256160477)

with st.sidebar:
    st.header("⚙️ 분석 변수")
    RATE = st.number_input("할인율 (%)", value=6.15) / 100
    TAX = st.number_input("세율 (%)", value=20.9) / 100
    PERIOD = st.number_input("상각기간 (년)", value=30)
    C_MAINT = st.number_input("유지비 (원/m)", value=8222)
    C_ADM_J = st.number_input("관리비 (원/전)", value=6209)
    C_ADM_M = st.number_input("관리비 (원/m)", value=13605)

if st.button("🚀 경제성 분석 실행", type="primary"):
    res = simulate_project(sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost, 
                           sim_jeon, RATE, TAX, PERIOD, C_MAINT, C_ADM_J, C_ADM_M)
    
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
              delta="투자 적격" if res['npv']>0 else "투자 부적격", delta_color="normal" if res['npv']>0 else "inverse")
    
    irr_display = f"{res['irr']*100:.2f} %" if res['irr'] > 0 else "계산 불가 (수익성 없음)"
    m2.metric("내부수익률 (IRR)", irr_display)
    
    dpp_display = "회수 불가" if res['dpp'] > PERIOD else f"{res['dpp']:.1f} 년"
    m3.metric("할인회수기간 (DPP)", dpp_display)

    # 요구사항: 세부 계산 근거를 바로 보여줌 (Expander 제거)
    st.subheader("🔎 세부 계산 근거")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info(f"""
        **1. 초기 순투자액(Year 0): {res['net_inv']:,.0f} 원**
        * 실제 내 돈이 들어가는 총액입니다.
        * 보조금과 분담금이 공사비보다 많으면 마이너스(유입)로 표시됩니다.
        
        **2. 연간 영업이익(EBIT): {res['ebit']:,.0f} 원**
        * 매출에서 원가, 판관비, 감가상각비를 뺀 금액입니다.
        """)
    with col_b:
        st.info(f"""
        **3. 연간 현금흐름(OCF): {res['ocf']:,.0f} 원**
        * 실제 매년 통장에 들어오거나 나가는 돈입니다.
        * (영업이익 - 세금 + 감가상각비)로 계산됩니다.
        """)

    if res['net_inv'] <= 0 and res['ebit'] < 0:
        st.warning("⚠️ **분석 결과 요약**: 보조금 덕분에 초기 비용은 없지만, 매년 운영할수록 적자가 발생하는 구조입니다. 따라서 NPV가 마이너스로 나타나며 투자 부적격 판정이 나옵니다.")

    # 누적 현금흐름 차트
    cf_df = pd.DataFrame({"Year": range(PERIOD+1), "Cumulative": np.cumsum(res['flows'])})
    st.line_chart(cf_df.set_index("Year"))
