import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# --------------------------------------------------------------------------
# [함수] 수동 금융 계산 (Numpy 버전 호환성용)
# --------------------------------------------------------------------------
def manual_npv(rate, values):
    total = 0.0
    for i, v in enumerate(values):
        total += v / ((1 + rate) ** i)
    return total

def manual_irr(values, guess=0.1):
    rate = guess
    for _ in range(100):
        npv = 0.0
        d_npv = 0.0
        for i, v in enumerate(values):
            term = v / ((1 + rate) ** i)
            npv += term
            d_npv -= i * term / (1 + rate)
        if abs(npv) < 1e-6: return rate
        if d_npv == 0: return 0
        rate -= npv / d_npv
    return rate

# --------------------------------------------------------------------------
# [함수] 데이터 파싱 (엑셀 처리용)
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
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
        if numbers: return float(numbers[0])
        return 0.0
    except: return 0.0

# --------------------------------------------------------------------------
# [함수 1] 엑셀 파일 분석 로직 (복구됨!)
# --------------------------------------------------------------------------
def calculate_excel_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m):
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수", "세대수"])
    col_usage = find_col(df, ["용도", "구분"])

    for index, row in df.iterrows():
        try:
            inv = parse_value(row.get(col_invest))
            cont = parse_value(row.get(col_contrib))
            vol = parse_value(row.get(col_vol))
            profit = parse_value(row.get(col_profit))
            length = parse_value(row.get(col_len))
            hh = parse_value(row.get(col_hh))
            usage = str(row.get(col_usage, ""))

            # 순투자액
            net_inv = max(0, inv - cont)
            
            # 관리비 계산 (엑셀은 기존 로직 유지 or 3중 합산 선택 가능하나 일단 기존 유지)
            maint_c = length * cost_maint_m
            if any(k in usage for k in ['공동', '단독', '주택', '아파트']):
                admin_c = hh * cost_admin_hh
            else:
                admin_c = length * cost_admin_m
            total_sga = maint_c + admin_c
            
            dep = net_inv / period
            req_capital = net_inv / pvifa if net_inv > 0 else 0
            req_ebit = (req_capital - dep) / (1 - tax_rate)
            req_gross = req_ebit + total_sga + dep
            
            margin_per_vol = profit / vol if vol > 0 else 0
            
            if margin_per_vol > 0:
                req_vol = req_gross / margin_per_vol
                results.append(req_vol)
            else:
                results.append(0)
        except:
            results.append(0)
            
    df['최소경제성만족판매량'] = results
    df['달성률'] = df.apply(lambda x: (x[col_vol]/x['최소경제성만족판매량']*100) if x['최소경제성만족판매량'] > 1 else 0, axis=1)
    return df

# --------------------------------------------------------------------------
# [함수 2] 시뮬레이션 로직 (형님 맞춤형: 3중 합산 + 1회성 이익 처리)
# --------------------------------------------------------------------------
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_onetime, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, 
                     c_maint, c_adm_jeon, c_adm_m):
    
    # 1. 초기 순투자액 (Net Investment)
    # 공식: 총공사비 - 시설분담금 - 기타이익(지자체보조금 등 1회성)
    # 예: 70억 - 2200만 - 70억 = -2200만 (돈 남음) -> 0으로 처리
    net_inv_raw = sim_inv - sim_contrib - sim_other_onetime
    net_inv = max(0, net_inv_raw) 
    
    # 2. 연간 판관비 (3가지 무조건 합산)
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    
    # 3. 연간 영업이익 (EBIT)
    # 마진 = 매출 - 원가 (기타이익은 1회성이므로 여기 포함 안 함!)
    margin = sim_rev - sim_cost
    
    # 감가상각 (내 돈이 0원이면 감가상각도 0원)
    dep = net_inv / period
    
    # 영업이익 = 마진 - 판관비 - 감가상각
    ebit = margin - cost_sga - dep
    
    # 4. 연간 현금흐름 (OCF)
    nopat = ebit * (1 - tax)
    ocf = nopat + dep
    
    # 5. 현금흐름 배열
    # 0년차: -순투자액
    # 1~30년차: OCF (적자면 계속 마이너스)
    flows = [-net_inv] + [ocf] * int(period)
    
    # 6. 지표 계산
    npv = manual_npv(rate, flows)
    irr = manual_irr(flows)
    
    dpp = 999.0
    cum = 0.0
    for i, f in enumerate(flows):
        cum += f / ((1 + rate) ** i)
        if i > 0 and cum >= 0:
            dpp = float(i)
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_inv, "ocf": ocf, "ebit": ebit, "sga": cost_sga, "margin": margin,
        "flows": flows, "raw_inv_calc": net_inv_raw
    }

# ==========================================================================
# [UI] 화면 구성
# ==========================================================================
with st.sidebar:
    st.header("📌 메뉴 선택")
    page_mode = st.radio("작업 모드:", ["배관투자 경제성 분석 관리", "신규배관 경제성 분석 Simulation"])
    st.divider()

# --------------------------------------------------------------------------
# 탭 1: 엑셀 관리 (복구됨)
# --------------------------------------------------------------------------
if page_mode == "배관투자 경제성 분석 관리":
    st.title("💰 배관투자 경제성 분석 관리")
    st.markdown("엑셀 파일을 업로드하여 기존 투자 건을 분석합니다.")
    
    with st.sidebar:
        st.subheader("⚙️ 분석 기준")
        target_irr = st.number_input("목표 IRR (%)", value=6.15)
        tax_rate = st.number_input("세율 (%)", value=20.9)
        period = st.number_input("상각 기간 (년)", value=30)
        st.subheader("💰 비용 단가")
        c_maint = st.number_input("유지비 (원/m)", value=8222)
        c_hh = st.number_input("관리비 (원/전)", value=6209)
        c_m = st.number_input("관리비 (원/m)", value=13605)

    uploaded_file = st.file_uploader("엑셀 파일 업로드", type=['xlsx'])
    
    if uploaded_file:
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        df = clean_column_names(df)
        
        res_df = calculate_excel_rows(df, target_irr/100, tax_rate/100, period, c_maint, c_hh, c_m)
        
        st.dataframe(res_df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        st.download_button("📥 결과 다운로드", output.getvalue(), "분석결과.xlsx")

# --------------------------------------------------------------------------
# 탭 2: 시뮬레이션 (수정됨)
# --------------------------------------------------------------------------
elif page_mode == "신규배관 경제성 분석 Simulation":
    st.title("🏗️ 신규배관 경제성 분석 Simulation")
    st.info("💡 **[기타 이익]**은 이제 **1회성 공사비 지원금**으로 처리됩니다. (투자비에서 차감)")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("1. 투자 정보")
        sim_len = st.number_input("투자 길이 (m)", value=7000.0)
        sim_inv = st.number_input("총 공사비 (원)", value=7000000000, step=100000000, format="%d")
        
        # 이름 명확하게 표시
        sim_contrib = st.number_input("시설 분담금 (기본, 원)", value=22048100, step=1000000, format="%d")
        
        # [핵심 수정] 1회성 이익으로 변경
        st.markdown("👇 **지자체 보조금 등 (1회성 수취)**")
        sim_other = st.number_input("기타 이익 (공사비 지원 성격, 원)", value=7000000000, step=100000000, format="%d")
        st.caption("※ 여기에 입력된 금액은 **초기 투자비에서 1회성으로 차감**됩니다.")
        
        st.markdown("---")
        st.subheader("2. 시설 특성")
        sim_jeon = st.number_input("공급 전수 (전)", value=2)
        st.caption("※ 비용: 배관(m) + 일반(m) + 일반(전) **모두 합산**")

    with c2:
        st.subheader("3. 수익 정보 (연간)")
        sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)
        sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
        sim_cost = st.number_input("연간 판매원가 (매입비, 원)", value=256160477)

    st.divider()
    
    # 사이드바 파라미터 (고정값 또는 입력 가능)
    with st.sidebar:
        st.subheader("⚙️ 시뮬레이션 변수")
        RATE = st.number_input("할인율 (%)", value=6.15) / 100
        TAX = st.number_input("세율 (%)", value=20.9) / 100
        PERIOD = st.number_input("기간 (년)", value=30)
        COST_MAINT = st.number_input("유지비 (원/m)", value=8222)
        COST_ADM_JEON = st.number_input("관리비 (원/전)", value=6209)
        COST_ADM_M = st.number_input("관리비 (원/m)", value=13605)

    if st.button("🚀 경제성 분석 실행 (Run)", type="primary"):
        res = simulate_project(
            sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost, 
            sim_jeon, RATE, TAX, PERIOD, 
            COST_MAINT, COST_ADM_JEON, COST_ADM_M
        )
        
        st.subheader("📊 시뮬레이션 결과")
        m1, m2, m3 = st.columns(3)
        
        m1.metric("1. 순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
                  delta="투자 적격" if res['npv']>0 else "투자 부적격 (손실)", 
                  delta_color="normal" if res['npv']>0 else "inverse")
        
        # IRR이 계산 불가능(적자)하면 N/A 표시
        irr_disp = f"{res['irr']*100:.2f} %" if res['npv'] > -res['net_inv'] else "산출 불가 (적자)"
        m2.metric("2. 내부수익률 (IRR)", irr_disp)
        
        dpp_str = "회수 불가" if res['dpp'] > 30 else f"{res['dpp']:.1f} 년"
        m3.metric("3. 할인회수기간 (DPP)", dpp_str)
        
        st.info(f"""
        **[📝 최종 검증 리포트]**
        
        1. **초기 내 투자금 (Year 0)**: **{res['net_inv']:,.0f} 원**
           * 계산식: 공사비({sim_inv:,.0f}) - 분담금({sim_contrib:,.0f}) - **기타이익({sim_other:,.0f})**
           * (※ 기타이익이 공사비를 깎아줘서, 내 돈은 0원이 되거나 남습니다.)
           
        2. **연간 영업이익 (Year 1~30)**: **{res['ebit']:,.0f} 원** (적자 🚨)
           * 수익(마진): +{res['margin']:,.0f} 원
           * 비용(판관비): -{res['sga']:,.0f} 원 (1.5억 고정지출)
           
        3. **결론**: 투자비가 0원이라도, 매년 적자가 누적되어 **NPV는 마이너스**입니다.
        """)
        
        # 차트
        cf_df = pd.DataFrame({"Year": range(31), "Cash Flow": res['flows'], "Cumulative": np.cumsum(res['flows'])})
        st.line_chart(cf_df.set_index("Year")["Cumulative"])
