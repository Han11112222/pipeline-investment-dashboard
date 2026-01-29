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

DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# --------------------------------------------------------------------------
# [함수] 데이터 전처리 & 파싱 (공통)
# --------------------------------------------------------------------------
def clean_column_names(df):
    """컬럼명 정규화"""
    df.columns = [str(c).replace("\n", "").replace(" ", "").replace("\t", "").strip() for c in df.columns]
    return df

def find_col(df, keywords):
    for col in df.columns:
        for kw in keywords:
            if kw in col:
                return col
    return None

def parse_value(value):
    try:
        if pd.isna(value) or value == '':
            return 0.0
        clean_str = str(value).replace(',', '')
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
        if numbers:
            return float(numbers[0])
        return 0.0
    except:
        return 0.0

# --------------------------------------------------------------------------
# [함수 1] 기존 분석 로직 (관리용 - 기존 기능 100% 복구)
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m, margin_override=None):
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    margin_debug = [] 
    
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수", "세대수"])
    col_usage = find_col(df, ["용도", "구분"])

    if not col_invest or not col_vol or not col_profit:
        return df, [], "❌ 핵심 컬럼 미발견"

    for index, row in df.iterrows():
        try:
            investment = parse_value(row.get(col_invest))
            contribution = parse_value(row.get(col_contrib))
            current_vol = parse_value(row.get(col_vol))
            current_profit = parse_value(row.get(col_profit))
            length = parse_value(row.get(col_len))
            households = parse_value(row.get(col_hh))
            usage_str = row.get(col_usage, "")

            if current_vol <= 0 or investment <= 0:
                results.append(0)
                margin_debug.append(0)
                continue

            net_investment = investment - contribution
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # 기존 엑셀 분석 로직 유지
            maint_cost = length * cost_maint_m
            if any(k in str(usage_str) for k in ['공동', '단독', '주택', '아파트']):
                admin_cost = households * cost_admin_hh
            else:
                admin_cost = length * cost_admin_m
            total_sga = maint_cost + admin_cost
            
            depreciation = investment / period
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)
            required_gross_margin = required_ebit + total_sga + depreciation
            
            calculated_margin = current_profit / current_vol
            if margin_override and margin_override > 0:
                final_margin = margin_override
            else:
                final_margin = calculated_margin

            if final_margin <= 0:
                results.append(0)
                margin_debug.append(0)
                continue

            required_volume = required_gross_margin / final_margin
            results.append(max(0, required_volume))
            margin_debug.append(final_margin)

        except:
            results.append(0)
            margin_debug.append(0)
    
    df['최소경제성만족판매량'] = results
    df['적용마진(원)'] = margin_debug
    
    df['달성률'] = df.apply(
        lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), 
        axis=1
    )

    return df, results, None

# --------------------------------------------------------------------------
# [함수 2] 신규 시뮬레이션 로직 (형님 맞춤형 - 3가지 비용 강제 합산)
# --------------------------------------------------------------------------

def calculate_internal_irr(cash_flows, guess=0.1):
    rate = guess
    for _ in range(100):
        val = sum([cf / ((1+rate)**t) for t, cf in enumerate(cash_flows)])
        if abs(val) < 1e-6: return rate
        d_val = sum([-t * cf / ((1+rate)**(t+1)) for t, cf in enumerate(cash_flows)])
        if d_val == 0: return 0
        rate -= val / d_val
    return rate if abs(rate) < 100 else 0

def simulate_project(inv_len, inv_amt, contrib, other_profit, vol, rev, cost, 
                     num_jeon, discount_rate, tax_rate, period,
                     cost_maint, cost_admin_jeon, cost_admin_m):
    
    # 1. 기초 데이터
    profit = rev - cost  # 마진
    
    # [중요] 순투자액 (투자비 - 분담금)
    # 형님이 70억, 70억 넣으면 0원이 됨.
    net_inv = max(0, inv_amt - contrib)
    
    # 2. 판관비 계산 (형님 요청: 3가지 무조건 합산)
    # 선택지 없이 무조건 다 더합니다.
    cost_1 = inv_len * cost_maint        # 배관 유지비 (m당)
    cost_2 = inv_len * cost_admin_m      # 일반 관리비 (m당) -> 여기가 큼 (약 9500만원)
    cost_3 = num_jeon * cost_admin_jeon  # 일반 관리비 (전당)
    
    total_sga = cost_1 + cost_2 + cost_3 # 합계: 약 1.5억
    
    # 3. 감가상각 & OCF
    # 회계적 감가상각비
    dep = inv_amt / period
    
    # 영업이익(EBIT) = 마진 - 판관비 - 감가상각
    # 마진(0.5억) - 판관비(1.5억) - 감가(2.3억) = -3.3억 (대규모 적자)
    ebit = (profit + other_profit) - total_sga - dep
    
    # NOPAT & OCF
    nopat = ebit * (1 - tax_rate)
    ocf = nopat + dep
    
    # 4. 현금흐름 배열
    cash_flows = [-net_inv] + [ocf] * int(period)
    
    # 5. 지표 계산
    npv = sum([cf / ((1 + discount_rate) ** t) for t, cf in enumerate(cash_flows)])
    irr = calculate_internal_irr(cash_flows)
    
    dpp = 999.0
    cum = 0
    for t, cf in enumerate(cash_flows):
        cum += cf / ((1 + discount_rate) ** t)
        if t > 0 and cum >= 0:
            dpp = float(t)
            break
            
    return {
        "npv": npv, "irr": irr, "dpp": dpp,
        "net_inv": net_inv, "ocf": ocf, "margin": profit, 
        "sga": total_sga, "ebit": ebit, "flows": cash_flows,
        "c1": cost_1, "c2": cost_2, "c3": cost_3
    }

# ==========================================================================
# [메인] 화면 구성 (사이드바 탭 복구됨)
# ==========================================================================

with st.sidebar:
    st.header("📌 메뉴 선택")
    # [복구] 기존 엑셀 관리 탭과 시뮬레이션 탭 분리
    page_mode = st.radio("작업 모드:", ["배관투자 경제성 분석 관리", "신규배관 경제성 분석 Simulation"])
    st.divider()

# --------------------------------------------------------------------------
# [화면 1] 배관투자 경제성 분석 관리 (기존 화면 복구 완료)
# --------------------------------------------------------------------------
if page_mode == "배관투자 경제성 분석 관리":
    with st.sidebar:
        st.subheader("📂 파일 설정")
        data_source = st.radio("소스", ("GitHub 파일", "엑셀 업로드"))
        uploaded_file = None
        if data_source == "엑셀 업로드":
            uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
        
        st.divider()
        st.subheader("⚙️ 분석 기준")
        target_irr_percent = st.number_input("목표 IRR (%)", value=6.15, format="%.2f", step=0.01)
        tax_rate_percent = st.number_input("세율 (%)", value=20.9, format="%.1f", step=0.1)
        period_input = st.number_input("상각 기간 (년)", value=30, step=1)
        
        st.subheader("💰 비용 단가 (2024년 기준)")
        cost_maint_m_input = st.number_input("유지비 (원/m)", value=8222)
        cost_admin_hh_input = st.number_input("일반관리비 (원/전)", value=6209)
        cost_admin_m_input = st.number_input("일반관리비 (원/m)", value=13605)

        st.divider()
        st.subheader("🔧 정밀 보정")
        margin_override_input = st.number_input("단위당 마진 강제 (원/MJ)", value=0.0, step=0.0001, format="%.4f")
        st.caption("* 0이면 자동 계산")

        target_irr = target_irr_percent / 100
        tax_rate = tax_rate_percent / 100

    st.title("💰 배관투자 경제성 분석 관리")
    st.markdown("💡 **기존 투자 건(2020~2024)에 대한 최소 판매량 및 달성률 분석**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("목표 IRR", f"{target_irr_percent:.2f}%")
    c2.metric("적용 세율", f"{tax_rate_percent}%")
    c3.metric("유지비", f"{cost_maint_m_input:,}원")
    c4.metric("적용 마진", f"{margin_override_input:.4f}" if margin_override_input > 0 else "자동")

    df = None
    if data_source == "GitHub 파일":
        if os.path.exists(DEFAULT_FILE_NAME):
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
        else:
            st.warning(f"⚠️ {DEFAULT_FILE_NAME} 없음")
    elif data_source == "엑셀 업로드" and uploaded_file:
        df = pd.read_excel(uploaded_file, engine='openpyxl')

    if df is not None:
        df = clean_column_names(df)
        result_df, margins, msg = calculate_all_rows(
            df, target_irr, tax_rate, period_input, 
            cost_maint_m_input, cost_admin_hh_input, cost_admin_m_input,
            margin_override_input
        )
        if msg:
            st.error(msg)
        else:
            st.divider()
            st.subheader("📊 분석 결과")
            view_cols = ["공사관리번호", "투자분석명", "용도", "연간판매량", "최소경제성만족판매량", "달성률", "적용마진"]
            final_df = pd.DataFrame()
            for col in view_cols:
                found = find_col(result_df, [col])
                if found: final_df[col] = result_df[found]
            
            st.dataframe(final_df, use_container_width=True, hide_index=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                result_df.to_excel(writer, index=False)
            st.download_button("📥 엑셀 다운로드", output.getvalue(), "분석결과.xlsx", "primary")

# --------------------------------------------------------------------------
# [화면 2] 신규배관 경제성 분석 Simulation (신규)
# --------------------------------------------------------------------------
elif page_mode == "신규배관 경제성 분석 Simulation":
    
    with st.sidebar:
        st.subheader("⚙️ 시뮬레이션 기준")
        sim_discount_rate = st.number_input("할인율 (Target IRR, %)", value=6.15, format="%.2f", step=0.01)
        sim_tax_rate = st.number_input("법인세율 (%)", value=20.9, format="%.1f", step=0.1)
        sim_period = st.number_input("사업 기간 (년)", value=30, step=1)
        
        st.subheader("💰 비용 단가 (2024년 기준)")
        sim_cost_maint = st.number_input("배관 유지비 (원/m)", value=8222)
        
        st.markdown("**일반관리비 단가 (두 가지)**")
        sim_cost_admin_jeon = st.number_input("일반관리비 (원/전)", value=6209)
        sim_cost_admin_m = st.number_input("일반관리비 (원/m)", value=13605)

    st.title("🏗️ 신규배관 경제성 분석 Simulation")
    st.markdown("💡 **신규 투자 건에 대해 NPV, IRR, 회수기간을 시뮬레이션합니다.**")
    st.warning("🚨 **[필독]** 판관비는 **[배관유지비(m) + 일반m당 + 일반전당]** 3가지를 **무조건 합산**하여 계산합니다.")
    
    st.divider()
    
    # 입력 폼
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. 투자 정보")
        # 기본값은 형님 말씀대로 제거(0으로 설정)하되, 형님이 직접 입력하시면 됩니다.
        sim_len = st.number_input("투자 길이 (m)", value=0.0, step=10.0, format="%.1f")
        sim_inv = st.number_input("총 공사비 (원)", value=0, step=1000000)
        sim_contrib = st.number_input("시설 분담금 (지원액, 원)", value=0, step=1000000)
        
        st.markdown("---")
        st.subheader("2. 시설 특성")
        st.info("ℹ️ 3가지 관리비가 모두 합산 적용됩니다.")
        sim_jeon = st.number_input("공급 전수 (전)", value=0, step=1)

    with col2:
        st.subheader("3. 수익 정보")
        sim_vol = st.number_input("연간 판매량 (MJ)", value=0.0, step=10000.0)
        sim_rev = st.number_input("연간 판매액 (매출, 원)", value=0, step=100000)
        sim_cost = st.number_input("연간 판매원가 (매입비, 원)", value=0, step=100000)
        sim_other = st.number_input("기타 이익 (원)", value=0, step=10000)
        
    st.divider()
    
    if st.button("🚀 경제성 분석 실행 (Run Analysis)", type="primary"):
        # 계산 함수 호출 (3가지 비용 무조건 합산 로직 사용)
        res = simulate_project(
            sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost,
            sim_jeon, sim_discount_rate/100, sim_tax_rate/100, sim_period,
            sim_cost_maint, sim_cost_admin_jeon, sim_cost_admin_m
        )
        
        # 결과
        st.subheader("📊 시뮬레이션 결과")
        m1, m2, m3 = st.columns(3)
        
        # NPV 표시 (적자면 빨간색)
        m1.metric("1. 순현재가치 (NPV)", f"{res['npv']:,.0f} 원", 
                  delta="투자 적격" if res['npv']>0 else "투자 부적격 (손실)", 
                  delta_color="normal" if res['npv']>0 else "inverse")
        
        irr_val = res['irr'] * 100
        m2.metric("2. 내부수익률 (IRR)", f"{irr_val:.2f} %", 
                  delta=f"목표 {sim_discount_rate}% 대비", 
                  delta_color="normal" if irr_val >= sim_discount_rate else "inverse")
        
        dpp_display = f"{res['dpp']:.1f} 년" if res['dpp'] < 999 else "회수 불가 (30년 초과)"
        m3.metric("3. 할인회수기간 (DPP)", dpp_display,
                  delta="원금 회수 시점", delta_color="off")
        
        # 상세 데이터 검증표
        st.error(f"""
        **[💰 비용 vs 수익 검산표]**
        
        **1. 0년차 순투자액 (Cash Out)** : **{res['net_inv']:,.0f} 원** (공사비 - 지원금)
           *(이 값이 0원이어야 합니다.)*
        
        **2. 연간 영업이익 (EBIT)** : **{res['ebit']:,.0f} 원** (적자 🚨)
           *(수익 {res['margin']:,.0f} - 판관비 {res['sga']:,.0f} - 감가상각)*
           
        **3. 연간 현금흐름 (OCF)** : **{res['ocf']:,.0f} 원**
           *(여기가 마이너스여야 NPV도 마이너스가 나옵니다.)*
        """)
        
        # 차트
        st.subheader("📈 30년 현금흐름")
        cf_df = pd.DataFrame({"연차": range(31), "현금흐름": res['flows'], "누적 현금흐름": np.cumsum(res['flows'])})
        
        t1, t2 = st.tabs(["연도별 흐름", "누적 흐름"])
        with t1: 
            st.bar_chart(cf_df.set_index("연차")["현금흐름"])
        with t2: 
            st.line_chart(cf_df.set_index("연차")["누적 현금흐름"])
