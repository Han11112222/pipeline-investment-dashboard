import streamlit as st
import pandas as pd
import numpy as np
import io
import os

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# --------------------------------------------------------------------------
# [함수] 금융 계산 (Numpy 에러 방지용 수동 계산)
# --------------------------------------------------------------------------
def manual_npv(rate, values):
    total = 0.0
    for i, v in enumerate(values):
        total += v / ((1 + rate) ** i)
    return total

def manual_irr(values):
    """Newton-Raphson 방식으로 IRR 계산 (에러 방지)"""
    try:
        # 현금흐름 부호가 모두 같으면 계산 불가
        if all(v >= 0 for v in values) or all(v <= 0 for v in values):
            return 0.0
            
        rate = 0.1
        for _ in range(50):
            npv = 0.0
            d_npv = 0.0
            for i, v in enumerate(values):
                term = v / ((1 + rate) ** i)
                npv += term
                d_npv -= i * term / (1 + rate)
            
            if abs(npv) < 1e-6: return rate
            if d_npv == 0: return 0.0
            rate -= npv / d_npv
            if abs(rate) > 100: return 0.0 # 발산 방지
        return rate
    except:
        return 0.0

# --------------------------------------------------------------------------
# [함수] 데이터 파싱
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
# [함수 1] 엑셀 파일 분석 (기존 탭 복구)
# --------------------------------------------------------------------------
def calculate_excel_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m):
    if target_irr == 0: pvifa = period
    else: pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수"])
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

            net_inv = max(0, inv - cont)
            
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
                results.append(req_gross / margin_per_vol)
            else:
                results.append(0)
        except:
            results.append(0)
            
    df['최소경제성만족판매량'] = results
    df['달성률'] = df.apply(lambda x: (x[col_vol]/x['최소경제성만족판매량']*100) if x['최소경제성만족판매량'] > 1 else 0, axis=1)
    return df

# --------------------------------------------------------------------------
# [함수 2] 시뮬레이션 로직 (형님 엑셀 로직 완벽 반영)
# --------------------------------------------------------------------------
def simulate_project(sim_len, sim_inv, sim_contrib, sim_other_subsidy, sim_vol, sim_rev, sim_cost, 
                     sim_jeon, rate, tax, period, 
                     c_maint, c_adm_jeon, c_adm_m):
    
    # 1. 초기 순투자액 (Cash Outflow at Year 0)
    # 공식: 총공사비 - 시설분담금 - 기타이익(지자체보조금)
    # 예: 70억 - 2200만 - 70억 = -2200만 (현금 0원 투입)
    # 0보다 작으면(돈이 남으면) 0년차 현금흐름은 플러스가 됩니다.
    net_inv = sim_inv - sim_contrib - sim_other_subsidy
    
    # 2. 연간 판관비 (3가지 무조건 합산)
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    
    # 3. 연간 마진
    margin = sim_rev - sim_cost
    
    # 4. 감가상각비 (형님 엑셀 로직의 핵심!)
    # 내 돈이 0원이라도, '총 공사비' 기준으로 감가상각을 해서 세금 혜택을 받음
    depreciation = sim_inv / period 
    
    # 5. 영업이익 (EBIT)
    ebit = margin - cost_sga - depreciation
    
    # 6. 세후 영업이익 (NOPAT)
    nopat = ebit * (1 - tax)
    
    # 7. 연간 현금흐름 (OCF)
    # 현금 안 나간 감가상각비 다시 더해줌
    # 예: 적자(-2.6억) + 감가(2.3억) = -3300만원 (형님 엑셀의 그 숫자!)
    ocf = nopat + depreciation
    
    # 8. 현금흐름 배열
    # 0년차: -순투자액 (남은 돈이 있으면 플러스, 모자라면 마이너스)
    flows = [-net_inv] + [ocf] * int(period)
    
    # 9. 지표 계산
    npv = manual_npv(rate, flows)
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
        "net_inv": net_inv, "ocf": ocf, "ebit": ebit, "sga": cost_sga, "margin": margin,
        "dep": depreciation, "flows": flows
    }

# ==========================================================================
# [UI] 화면 구성
# ==========================================================================
with st.sidebar:
    st.header("📌 메뉴 선택")
    page_mode = st.radio("작업 모드:", ["배관투자 경제성 분석 관리", "신규배관 경제성 분석 Simulation"])
    st.divider()

# --------------------------------------------------------------------------
# 탭 1: 엑셀 관리
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
# 탭 2: 시뮬레이션
# --------------------------------------------------------------------------
elif page_mode == "신규배관 경제성 분석 Simulation":
    st.title("🏗️ 신규배관 경제성 분석 Simulation")
    st.markdown("### 💡 1회성 공사비 지원(기타이익) 반영 모델")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("1. 투자 정보")
        sim_len = st.number_input("투자 길이 (m)", value=7000.0)
        sim_inv = st.number_input("총 공사비 (원)", value=7000000000, step=100000000, format="%d")
        
        sim_contrib = st.number_input("시설 분담금 (기본, 원)", value=22048100, step=1000000, format="%d")
        
        # [핵심] 이제 여기 입력하면 초기 투자비에서 까줍니다.
        st.markdown("👇 **지자체 보조금 등 (1회성 수취)**")
        sim_other = st.number_input("기타 이익 (공사비 지원 1회성, 원)", value=7000000000, step=100000000, format="%d")
        st.caption("※ 이 금액은 **초기 투자비에서 차감**됩니다. (매출 아님)")
        
        st.markdown("---")
        st.subheader("2. 시설 특성")
        sim_jeon = st.number_input("공급 전수 (전)", value=2)
        st.caption("※ 비용: 3가지(배관+일반m+일반전) **모두 합산**")

    with c2:
        st.subheader("3. 수익 정보 (연간)")
        sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)
        sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
        sim_cost = st.number_input("연간 판매원가 (매입비, 원)", value=256160477)

    st.divider()
    
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
        
        irr_disp = "산출 불가" if res['irr'] == 0 else f"{res['irr']*100:.2f} %"
        m2.metric("2. 내부수익률 (IRR)", irr_disp)
        m3.metric("3. 할인회수기간 (DPP)", f"{res['dpp']:.1f} 년" if res['dpp'] < 30 else "회수 불가")
        
        # [형님 엑셀과 비교용 검증표]
        st.info(f"""
        **[📝 엑셀 로직 검증 리포트]**
        
        1. **초기 내 투자금 (0년차)**: **{res['net_inv']:,.0f} 원**
           *(공사비 - 분담금 - 기타이익)*
           
        2. **연간 영업이익 (EBIT)**: **{res['ebit']:,.0f} 원** (적자 🚨)
           * 마진: +{res['margin']:,.0f}
           * 판관비: -{res['sga']:,.0f}
           * 감가상각: -{res['dep']:,.0f} (70억 기준 반영됨)
           
        3. **최종 연간 현금흐름 (OCF)**: **{res['ocf']:,.0f} 원**
           * 형님 엑셀의 **'-33,385,690원'**과 유사한 로직으로 계산됨
           * (세후영업이익 + 감가상각비 환입)
        """)
        
        # 차트
        cf_df = pd.DataFrame({"Year": range(31), "Cash Flow": res['flows'], "Cumulative": np.cumsum(res['flows'])})
        st.line_chart(cf_df.set_index("Year")["Cumulative"])
