import streamlit as st
import pandas as pd
import numpy as np

# [설정] 페이지 기본
st.set_page_config(page_title="도시가스 경제성 분석기 v2.5", layout="wide")

def manual_npv(rate, values):
    return sum(v / ((1 + rate) ** i) for i, v in enumerate(values))

def manual_irr(values):
    """비정상 흐름 시 None 반환"""
    # 초기 유입(+), 이후 지속 지출(-)인 경우 경제적 의미의 IRR 산출 불가
    if values[0] >= 0:
        return None
    # 전체 흐름 합계가 마이너스인 경우 (수익성 없음)
    if sum(values) <= 0:
        return None
    try:
        import numpy_financial as npf
        res = npf.irr(values)
        return res if not np.isnan(res) else None
    except:
        return None

# [핵심 로직]
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_subsidy, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, c_maint, c_adm_jeon, c_adm_m):
    
    net_inv = sim_inv - sim_contrib - sim_other_subsidy
    margin = sim_rev - sim_cost
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    depreciation = sim_inv / period 
    
    ebit = margin - cost_sga - depreciation
    net_income = ebit * (1 - tax) 
    ocf = net_income + depreciation
    
    flows = [-net_inv] + [ocf] * int(period)
    npv = manual_npv(rate, flows)
    irr = manual_irr(flows)
    
    # 사유 판별
    irr_reason = ""
    if net_inv <= 0:
        irr_reason = "초기 투자비 0원 이하(자본 투입 없음)"
    elif sum(flows) <= 0:
        irr_reason = "총 현금흐름 마이너스(운영 적자 지속)"

    return {
        "npv": npv, "irr": irr, "irr_reason": irr_reason, "net_inv": net_inv, 
        "ocf": ocf, "ebit": ebit, "net_income": net_income, "flows": flows
    }

# [UI 구성]
st.title("🏗️ 신규배관 경제성 분석 Simulation")

with st.sidebar:
    st.header("⚙️ 분석 변수")
    RATE = st.number_input("할인율 (%)", value=6.15, step=0.01) / 100
    TAX = st.number_input("법인세율+주민세율 (%)", value=20.9) / 100
    PERIOD = st.number_input("분석 및 상각기간 (년)", value=30)
    COST_MAINT = st.number_input("유지비 (원/m)", value=8222)
    COST_ADM_J = st.number_input("관리비 (원/전)", value=6209)
    COST_ADM_M = st.number_input("관리비 (원/m)", value=13605)

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. 투자 정보")
    sim_len = st.number_input("투자 길이 (m)", value=7000.0)
    sim_inv = st.number_input("총 공사비 (원)", value=7000000000, format="%d")
    sim_contrib = st.number_input("시설 분담금 (원)", value=22048100, format="%d")
    sim_other = st.number_input("기타 이익 (보조금, 원)", value=7000000000, format="%d")
    sim_jeon = st.number_input("공급 전수 (전)", value=2)

with c2:
    st.subheader("2. 수익 정보 (연간)")
    sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)
    sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
    sim_cost = st.number_input("연간 판매원가 (원)", value=256160477)

if st.button("🚀 경제성 분석 실행", type="primary"):
    res = simulate_project(sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost, 
                           sim_jeon, RATE, TAX, PERIOD, COST_MAINT, COST_ADM_J, COST_ADM_M)
    
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
              delta="투자 적격" if res['npv']>0 else "투자 부적격", delta_color="normal" if res['npv']>0 else "inverse")
    
    # IRR 오류 처리 반영
    if res['irr'] is None:
        m2.metric("내부수익률 (IRR)", "계산 불가")
        st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;🚩 **사유**: {res['irr_reason']}")
    else:
        m2.metric("내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
        
    m3.metric("할인회수기간 (DPP)", "회수 불가")

    st.subheader("🔎 세부 계산 근거 (엑셀 로직 동기화)")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info(f"**초기 순투자액(Year 0): {res['net_inv']:,.0f} 원** \n(마이너스면 초기 자금 유입을 의미합니다.)")
        st.info(f"**세후 당기손익: {res['net_income']:,.0f} 원**")
    with col_b:
        st.info(f"**세후 수요개발 기대이익(OCF): {res['ocf']:,.0f} 원** \n(엑셀 시트 최하단 현금흐름과 일치합니다.)")

    cf_df = pd.DataFrame({"Year": range(PERIOD+1), "Cumulative": np.cumsum(res['flows'])})
    st.line_chart(cf_df.set_index("Year"))
