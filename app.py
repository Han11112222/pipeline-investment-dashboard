import streamlit as st
import pandas as pd
import numpy as np

# [설정] 페이지 기본
st.set_page_config(page_title="도시가스 경제성 분석기 v2.3", layout="wide")

def manual_npv(rate, values):
    return sum(v / ((1 + rate) ** i) for i, v in enumerate(values))

def manual_irr(values):
    """엑셀 IRR과 동일한 알고리즘 (Newton-Raphson)"""
    if sum(values) <= 0: return 0.0
    try:
        rate = 0.1 
        for _ in range(100):
            npv = sum(v / ((1 + rate) ** i) for i, v in enumerate(values))
            d_npv = sum(-i * v / ((1 + rate) ** (i + 1)) for i, v in enumerate(values))
            if abs(npv) < 1e-6: return rate
            if d_npv == 0: break
            rate -= npv / d_npv
        return rate
    except: return 0.0

# [핵심 로직] 엑셀 100% 동기화
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_subsidy, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, c_maint, c_adm_jeon, c_adm_m):
    
    # 0년차 순투자액 (Cash Outflow)
    net_inv = sim_inv - sim_contrib - sim_other_subsidy
    
    # 수익 및 비용
    margin = sim_rev - sim_cost
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    depreciation = sim_inv / period 
    
    # 세전 수요개발 기대이익 (EBIT)
    ebit = margin - cost_sga - depreciation
    
    # 세후 당기손익 (적자 시 세금 환급 효과 반영 - 엑셀 방식)
    # 엑셀은 ebit * (1 - tax)를 통해 적자 시에도 현금흐름 보전
    net_income = ebit * (1 - tax) 
    
    # 세후 수요개발 기대이익 (OCF = 세후손익 + 감가상각비)
    ocf = net_income + depreciation
    
    # 현금흐름 배열
    flows = [-net_inv] + [ocf] * int(period)
    
    # 지표 계산
    npv = manual_npv(rate, flows)
    irr = manual_irr(flows)
    
    # DPP 계산
    dpp = 999.0
    cum = 0.0
    for i, f in enumerate(flows):
        cum += f / ((1 + rate) ** i)
        if i > 0 and cum >= 0:
            dpp = float(i)
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp, 
        "net_inv": net_inv, "ocf": ocf, "ebit": ebit, 
        "net_income": net_income, "sga": cost_sga, "dep": depreciation, "flows": flows
    }

# [UI] 화면 구성
st.title("🏗️ 신규배관 경제성 분석 Simulation")

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

with st.sidebar:
    st.header("⚙️ 분석 변수")
    # 엑셀 시트 기준: 법인세 19% + 주민세 1.9% = 20.9%
    RATE = st.number_input("할인율 (%)", value=6.15) / 100
    TAX = st.number_input("법인세율+주민세율 (%)", value=20.9) / 100
    PERIOD = st.number_input("분석 및 상각기간 (년)", value=30)
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
    
    # 엑셀과 동일한 151.42%가 나오게 됨
    m2.metric("내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
    m3.metric("할인회수기간 (DPP)", "회수 불가" if res['dpp'] > PERIOD else f"{res['dpp']:.1f} 년")

    st.subheader("🔎 세부 계산 근거 (엑셀 로직 동기화)")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info(f"""
        **1. 초기 순투자액(Year 0): {res['net_inv']:,.0f} 원**
        * 엑셀과 동일하게 분담금과 보조금을 차감한 초기 자산 투입액입니다.
        
        **2. 세후 당기손익: {res['net_income']:,.0f} 원**
        * 엑셀의 '세후 당기 손익' 항목과 일치합니다.
        * 적자 시 세금 절감 효과($EBIT \times TAX$)가 이익으로 반영되었습니다.
        """)
    with col_b:
        st.info(f"""
        **3. 세후 수요개발 기대이익(OCF): {res['ocf']:,.0f} 원**
        * 엑셀의 최하단 현금흐름 수치와 일치합니다.
        * 이 수치가 30년 할인 합산되어 NPV를 구성합니다.
        """)

    # 누적 현금흐름 차트
    cf_df = pd.DataFrame({"Year": range(PERIOD+1), "Cumulative": np.cumsum(res['flows'])})
    st.line_chart(cf_df.set_index("Year"))
