import streamlit as st
import pandas as pd
import numpy as np
import io

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기 v2", layout="wide")

# --------------------------------------------------------------------------
# [함수] 금융 계산 (수학적 보정 포함)
# --------------------------------------------------------------------------
def manual_npv(rate, values):
    total = 0.0
    for i, v in enumerate(values):
        total += v / ((1 + rate) ** i)
    return total

def manual_irr(values):
    """
    Newton-Raphson 방식으로 IRR 계산.
    비정상적 흐름(초기 유입 후 지속 적자)일 경우 0을 반환하도록 보정.
    """
    # 0년차에 유입(+)이 있고 이후 계속 지출(-)이면 수학적으로 매우 높은 IRR이 나옴
    # 이를 방지하기 위해 합계가 음수이면 수익률이 없는 것으로 간주
    if sum(values) <= 0:
        return 0.0
        
    try:
        if all(v >= 0 for v in values) or all(v <= 0 for v in values):
            return 0.0
            
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
            if abs(rate) > 10: return 0.0 # 현실적이지 않은 수익률(1000% 등) 차단
            
        return rate
    except:
        return 0.0

# --------------------------------------------------------------------------
# [함수] 데이터 파싱 및 로직
# --------------------------------------------------------------------------
def clean_column_names(df):
    df.columns = [str(c).replace("\n", "").replace(" ", "").replace("\t", "").strip() for c in df.columns]
    return df

def find_col(df, keywords):
    for col in df.columns:
        for kw in keywords:
            if kw in col: return col
    return None

def parse_value(value):
    try:
        if pd.isna(value) or value == '': return 0.0
        clean_str = str(value).replace(',', '')
        import re
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
        if numbers: return float(numbers[0])
        return 0.0
    except: return 0.0

# --------------------------------------------------------------------------
# [핵심 로직] 시뮬레이션 (수정 버전)
# --------------------------------------------------------------------------
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_subsidy, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, 
                     c_maint, c_adm_jeon, c_adm_m):
    
    # 1. 초기 순투자액 (Year 0)
    # 총공사비 - 시설분담금 - 기타이익(보조금)
    net_inv = sim_inv - sim_contrib - sim_other_subsidy
    
    # 2. 연간 판관비
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    
    # 3. 영업이익 (EBIT)
    margin = sim_rev - sim_cost
    depreciation = sim_inv / period 
    ebit = margin - cost_sga - depreciation
    
    # 4. 연간 현금흐름 (OCF)
    nopat = ebit * (1 - tax) if ebit > 0 else ebit # 적자시 세금환급은 보수적으로 제외하거나 ebit 그대로 반영
    ocf = nopat + depreciation
    
    # 5. 현금흐름 배열 (0년차 지출은 -net_inv)
    flows = [-net_inv] + [ocf] * int(period)
    
    # 6. 지표 계산
    npv = manual_npv(rate, flows)
    
    # 보정 로직: NPV가 음수이고 매년 들어오는 돈(OCF)이 적자면 IRR은 의미 없음
    if npv <= 0 and ocf <= 0:
        irr = 0.0
    else:
        irr = manual_irr(flows)
    
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
with st.sidebar:
    st.header("📌 메뉴 선택")
    page_mode = st.radio("작업 모드:", ["배관투자 경제성 분석 관리", "신규배관 경제성 분석 Simulation"])
    st.divider()

if page_mode == "배관투자 경제성 분석 관리":
    st.title("💰 배관투자 경제성 분석 관리")
    # (기존 엑셀 업로드 로직 동일 - 생략 가능하나 구조 유지를 위해 포함)
    uploaded_file = st.file_uploader("엑셀 파일 업로드", type=['xlsx'])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        st.write("파일이 로드되었습니다.")

elif page_mode == "신규배관 경제성 분석 Simulation":
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
        st.subheader("3. 수익 정보 (연간)")
        sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
        sim_cost = st.number_input("연간 판매원가 (원)", value=256160477)
        sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)

    with st.sidebar:
        st.subheader("⚙️ 변수 설정")
        RATE = st.number_input("할인율 (%)", value=6.15) / 100
        TAX = st.number_input("세율 (%)", value=20.9) / 100
        PERIOD = st.number_input("상각기간 (년)", value=30)
        C_MAINT = st.number_input("유지비 (원/m)", value=8222)
        C_ADM_J = st.number_input("관리비 (원/전)", value=6209)
        C_ADM_M = st.number_input("관리비 (원/m)", value=13605)

    if st.button("🚀 경제성 분석 실행", type="primary"):
        res = simulate_project(sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost, 
                               sim_jeon, RATE, TAX, PERIOD, C_MAINT, C_ADM_J, C_ADM_M)
        
        # 결과 대시보드
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
                  delta="투자 적격" if res['npv']>0 else "투자 부적격", delta_color="normal" if res['npv']>0 else "inverse")
        
        # IRR 표시 로직 수정
        irr_display = f"{res['irr']*100:.2f} %" if res['irr'] > 0 else "계산 불가 (수익성 없음)"
        m2.metric("내부수익률 (IRR)", irr_display)
        
        dpp_display = "회수 불가" if res['dpp'] > PERIOD else f"{res['dpp']:.1f} 년"
        m3.metric("할인회수기간 (DPP)", dpp_display)

        # 상세 리포트
        with st.expander("🔎 세부 계산 근거 보기"):
            st.write(f"- **초기 순투자액**: {res['net_inv']:,.0f} 원 (마이너스면 초기 유입)")
            st.write(f"- **연간 영업이익(EBIT)**: {res['ebit']:,.0f} 원")
            st.write(f"- **연간 현금흐름(OCF)**: {res['ocf']:,.0f} 원")
            if res['net_inv'] <= 0 and res['ebit'] < 0:
                st.warning("⚠️ 초기 투자금이 보조금으로 인해 0원 이하이나, 운영 수익이 적자입니다. 이 경우 IRR 수치는 수학적 착시를 일으키므로 NPV를 기준으로 판단해야 합니다.")

        # 누적 현금흐름 차트
        cf_df = pd.DataFrame({"Year": range(PERIOD+1), "Cumulative": np.cumsum(res['flows'])})
        st.line_chart(cf_df.set_index("Year"))
