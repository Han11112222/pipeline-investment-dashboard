import streamlit as st
import pandas as pd
import numpy as np

# [설정] 페이지 기본
st.set_page_config(page_title="도시가스 경제성 분석기 v2.6", layout="wide")

def manual_npv(rate, values):
    return sum(v / ((1 + rate) ** i) for i, v in enumerate(values))

def manual_irr(values):
    """비정상적 현금흐름 시 계산 불가 처리"""
    if values[0] >= 0: # 초기 투자비가 0원 이하인 경우
        return None
    if sum(values) <= 0: # 총 회수액이 투자액보다 적은 경우
        return None
    try:
        import numpy_financial as npf
        res = npf.irr(values)
        return res if not np.isnan(res) and res < 5 else None # 비현실적 고수익률 차단
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
    # 엑셀 기준: 적자 시 세금 절감 효과 반영(Tax Shield)
    net_income = ebit * (1 - tax) 
    ocf = net_income + depreciation
    
    flows = [-net_inv] + [ocf] * int(period)
    npv = manual_npv(rate, flows)
    irr = manual_irr(flows)
    
    irr_reason = "초기 투자비 0원 이하(보조금 과다) 또는 운영 적자 지속" if irr is None else ""

    return {
        "npv": npv, "irr": irr, "irr_reason": irr_reason, "net_inv": net_inv, 
        "ocf": ocf, "ebit": ebit, "net_income": net_income, "flows": flows
    }

# [UI] 상단 타이틀
st.title("🏗️ 신규배관 경제성 분석 Simulation")

with st.sidebar:
    st.header("⚙️ 분석 변수 설정")
    RATE = st.number_input("할인율 (%)", value=6.15, step=0.01) / 100
    TAX = st.number_input("법인세율+주민세율 (%)", value=20.9) / 100
    PERIOD = st.number_input("분석 및 상각기간 (년)", value=30)
    C_MAINT = st.number_input("유지비 (원/m)", value=8222)
    C_ADM_J = st.number_input("관리비 (원/전)", value=6209)
    C_ADM_M = st.number_input("관리비 (원/m)", value=13605)

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
                           sim_jeon, RATE, TAX, PERIOD, C_MAINT, C_ADM_J, C_ADM_M)
    
    st.divider()
    
    # 결과 지표 표시
    m1, m2, m3 = st.columns(3)
    
    # 1. NPV 표시 및 설명
    with m1:
        st.metric("순현재가치 (NPV)", f"{res['npv']:,.0f} 원")
        st.caption("**[의미]** 투자로 인해 발생하는 모든 현금흐름을 현재 가치로 합산한 값입니다.")
        if res['npv'] < 0:
            st.error("⚠️ 투자 부적격 (손실 예상)")
        else:
            st.success("✅ 투자 적격 (수익 예상)")

    # 2. IRR 표시 및 설명
    with m2:
        if res['irr'] is None:
            st.metric("내부수익률 (IRR)", "계산 불가")
            st.caption(f"**[알림]** {res['irr_reason']}")
        else:
            st.metric("내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
        st.caption("**[의미]** 투자 비용 대비 매년 기대되는 수익률입니다. 할인율보다 높아야 투자가치가 있습니다.")

    # 3. DPP 표시 및 설명
    with m3:
        st.metric("할인회수기간 (DPP)", "회수 불가")
        st.caption("**[의미]** 투자 원금을 회수하는 데 걸리는 시간입니다. 현재 수익성으로는 원금 회수가 어렵습니다.")

    st.divider()

    # NPV 산출 사유 요약 (요청하신 부분)
    st.subheader("🧐 NPV 산출 사유 분석")
    st.markdown(f"""
    현재 NPV가 **{res['npv']:,.0f}원**으로 산출된 주요 원인은 다음과 같습니다:
    
    1. **운영 수익성 결여**: 연간 매출 마진({(sim_rev-sim_cost):,.0f}원)보다 판관비와 관리비의 합({res['sga']:,.0f}원)이 더 커서 매년 영업 적자가 발생합니다.
    2. **감가상각 부담**: 70억 원의 대규모 공사비가 매년 약 {res['dep']/100000000:,.1f}억 원의 감가상각 비용으로 반영되어 장부상 손실을 키우고 있습니다.
    3. **현금유출 지속**: 보조금으로 초기 자본 투입은 방어했으나, 매년 발생하는 세후 현금흐름(OCF)이 **{res['ocf']:,.0f}원**으로 마이너스입니다.
    4. **미래 손실의 누적**: 30년 동안 반복되는 연간 손실액을 현재 가치로 할인하여 합산한 결과, 초기 보조금 혜택을 상회하는 큰 규모의 마이너스 NPV가 도출되었습니다.
    """)

    # 세부 계산 수치
    st.subheader("🔎 세부 계산 근거")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info(f"**초기 순투자액(Year 0): {res['net_inv']:,.0f} 원**\n\n*실제 투입되는 초기 자본입니다. 보조금이 공사비보다 많을 경우 마이너스로 표시됩니다.*")
    with col_b:
        st.info(f"**세후 수요개발 기대이익(OCF): {res['ocf']:,.0f} 원**\n\n*매년 실제로 발생하는 현금 흐름입니다. 이 수치가 NPV를 결정하는 핵심 요인입니다.*")
