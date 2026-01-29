import streamlit as st
import pandas as pd
import numpy as np

# [설정] 페이지 기본
st.set_page_config(page_title="도시가스 경제성 분석기 v2.7", layout="wide")

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
        return res if not np.isnan(res) and res < 5 else None
    except:
        return None

# [핵심 로직]
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_subsidy, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, c_maint, c_adm_jeon, c_adm_m):
    
    # 0년차 초기 투자비
    net_inv = sim_inv - sim_contrib - sim_other_subsidy
    
    # 수익 및 비용 계산
    margin = sim_rev - sim_cost
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    depreciation = sim_inv / period 
    
    # 세전 영업이익 (EBIT)
    ebit = margin - cost_sga - depreciation
    
    # 세금 환급 효과 반영 (Tax Shield)
    net_income = ebit * (1 - tax) 
    
    # 세후 수요개발 기대이익 (OCF = 세후당기손익 + 감가상각비)
    ocf = net_income + depreciation
    
    # 전체 현금흐름 배열
    flows = [-net_inv] + [ocf] * int(period)
    
    # 지표 산출
    npv = manual_npv(rate, flows)
    irr = manual_irr(flows)
    
    irr_reason = "초기 투자비 0원 이하(보조금 과다) 또는 운영 적자 지속" if irr is None else ""

    return {
        "npv": npv, "irr": irr, "irr_reason": irr_reason, "net_inv": net_inv, 
        "ocf": ocf, "ebit": ebit, "net_income": net_income, "sga": cost_sga, 
        "dep": depreciation, "flows": flows, "margin": margin
    }

# [UI] 타이틀 및 입력부
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
    
    # 결과 지표 상단 표시
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("순현재가치 (NPV)", f"{res['npv']:,.0f} 원")
        if res['npv'] < 0: st.error("⚠️ 투자 부적격 (손실 예상)")
        else: st.success("✅ 투자 적격 (수익 예상)")
        st.caption("[의미] 모든 현금흐름을 현재 가치로 합산한 값입니다.")

    with m2:
        if res['irr'] is None:
            st.metric("내부수익률 (IRR)", "계산 불가")
            st.caption(f"[알림] {res['irr_reason']}")
        else:
            st.metric("내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
        st.caption("[의미] 투자 비용 대비 매년 기대되는 수익률입니다.")

    with m3:
        st.metric("할인회수기간 (DPP)", "회수 불가")
        st.caption("[의미] 투자 원금을 회수하는 데 걸리는 시간입니다.")

    st.divider()

    # NPV 산출 사유 분석 (에러 수정 및 문구 추가)
    st.subheader("🧐 NPV 산출 사유 분석")
    st.markdown(f"""
    현재 NPV가 **{res['npv']:,.0f}원**으로 산출된 주요 원인은 다음과 같습니다:
    
    1. **운영 수익성 결여**: 연간 매출 마진({res['margin']:,.0f}원)보다 판관비 합계({res['sga']:,.0f}원)가 더 커서 본원적인 영업 적자 상태입니다.
    2. **감가상각 부담**: 총 공사비 70억 원에 대해 매년 **{res['dep']:,.0f}원**의 감가상각비가 발생하여 비용 부담을 가중시키고 있습니다.
    3. **현금흐름 적자 지속**: 세금 절감 효과와 감가상각비 환입을 고려하더라도, 매년 **{res['ocf']:,.0f}원**의 **세후 수요개발 기대이익(적자)**이 발생하고 있습니다.
    4. **미래 가치 누적**: 매년 발생하는 약 {abs(res['ocf'])/1000000:,.1f}백만 원의 손실이 {PERIOD}년 동안 누적 및 할인되어 최종 NPV에 반영되었습니다.
    """)

    # 세부 수치 요약
    st.subheader("🔎 세부 계산 근거")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info(f"**초기 순투자액(Year 0): {res['net_inv']:,.0f} 원**\n\n(공사비 - 분담금 - 보조금)")
    with col_b:
        st.info(f"**세후 수요개발 기대이익(OCF): {res['ocf']:,.0f} 원**\n\n(연간 실제 현금 흐름)")

    # 차트
    cf_df = pd.DataFrame({"Year": range(PERIOD+1), "Cumulative": np.cumsum(res['flows'])})
    st.line_chart(cf_df.set_index("Year"))
