import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정] 페이지 기본
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석 시스템", layout="wide")

# --------------------------------------------------------------------------
# [공통 함수] 데이터 파싱 및 금융 계산
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
        return float(numbers[0]) if numbers else 0.0
    except: return 0.0

def manual_npv(rate, values):
    return sum(v / ((1 + rate) ** i) for i, v in enumerate(values))

def manual_irr(values):
    if values[0] >= 0 or sum(values) <= 0: return None
    try:
        # 간단한 Newton-Raphson 로직 혹은 numpy-financial 사용 가능
        import numpy_financial as npf
        res = npf.irr(values)
        return res if not np.isnan(res) and res < 5 else None
    except: return None

# --------------------------------------------------------------------------
# [기능 1] 엑셀 대량 분석 로직 (모드 1용)
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m, margin_override=None):
    if target_irr == 0: pvifa = period
    else: pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results, margin_debug = [], []
    col_invest = find_col(df, ["배관투자", "투자금액"])
    col_contrib = find_col(df, ["시설분담금", "분담금"])
    col_vol = find_col(df, ["연간판매량", "판매량계"])
    col_profit = find_col(df, ["연간판매수익", "판매수익"])
    col_len = find_col(df, ["길이", "연장"])
    col_hh = find_col(df, ["계획전수", "전수", "세대수"])
    col_usage = find_col(df, ["용도", "구분"])

    if not col_invest or not col_vol or not col_profit:
        return df, [], "❌ 핵심 컬럼 미발견"

    for _, row in df.iterrows():
        try:
            inv = parse_value(row.get(col_invest))
            cont = parse_value(row.get(col_contrib))
            vol = parse_value(row.get(col_vol))
            profit = parse_value(row.get(col_profit))
            length = parse_value(row.get(col_len))
            hh = parse_value(row.get(col_hh))
            usage = str(row.get(col_usage, ""))

            if vol <= 0 or inv <= 0:
                results.append(0); margin_debug.append(0); continue

            net_inv = inv - cont
            req_cap = net_inv / pvifa if net_inv > 0 else 0
            maint_c = length * cost_maint_m
            admin_c = hh * cost_admin_hh if any(k in usage for k in ['공동', '단독', '주택', '아파트']) else length * cost_admin_m
            total_sga = maint_c + admin_c
            dep = inv / period
            req_ebit = (req_cap - dep) / (1 - tax_rate)
            req_gross = req_ebit + total_sga + dep
            
            calc_margin = profit / vol if vol > 0 else 0
            final_margin = margin_override if margin_override and margin_override > 0 else calc_margin
            
            if final_margin <= 0:
                results.append(0); margin_debug.append(0); continue
            
            results.append(max(0, req_gross / final_margin))
            margin_debug.append(final_margin)
        except:
            results.append(0); margin_debug.append(0)

    df['최소경제성만족판매량'] = results
    df['적용마진(원)'] = margin_debug
    df['달성률'] = df.apply(lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), axis=1)
    return df, results, None

# --------------------------------------------------------------------------
# [UI] 사이드바 메뉴 (모드 선택)
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 메뉴 선택")
    page_mode = st.radio("작업 모드", ["배관투자 경제성 분석 관리", "신규배관 경제성 분석 Simulation"])
    st.divider()
    
    # 공통 변수 설정
    st.subheader("⚙️ 분석 기준")
    target_irr_percent = st.number_input("목표 IRR (%)", value=6.15, format="%.2f", step=0.01)
    tax_rate_percent = st.number_input("세율 (%)", value=20.9, format="%.1f", step=0.1)
    period_input = st.number_input("분석 및 상각 기간 (년)", value=30, step=1)
    
    st.subheader("💰 비용 단가")
    cost_maint_m = st.number_input("유지비 (원/m)", value=8222)
    cost_admin_hh = st.number_input("관리비 (원/전)", value=6209)
    cost_admin_m = st.number_input("관리비 (원/m)", value=13605)
    
    target_irr = target_irr_percent / 100
    tax_rate = tax_rate_percent / 100

# --------------------------------------------------------------------------
# [모드 1] 배관투자 경제성 분석 관리 (대량 분석)
# --------------------------------------------------------------------------
if page_mode == "배관투자 경제성 분석 관리":
    st.title("💰 배관투자 경제성 분석 관리")
    st.markdown("💡 **엑셀 업로드 기반 다수 프로젝트 현황 분석 및 시각화**")
    
    with st.sidebar:
        st.divider()
        data_source = st.radio("데이터 소스", ("GitHub 파일", "엑셀 업로드"))
        uploaded_file = st.file_uploader("파일 업로드", type=['xlsx']) if data_source == "엑셀 업로드" else None
        margin_override = st.number_input("단위당 마진 강제 (원/MJ)", value=0.0, step=0.0001, format="%.4f")

    df = None
    if data_source == "GitHub 파일":
        if os.path.exists("리스트_20260129.xlsx"): df = pd.read_excel("리스트_20260129.xlsx")
        else: st.warning("⚠️ 기본 파일을 찾을 수 없습니다.")
    elif uploaded_file: df = pd.read_excel(uploaded_file)

    if df is not None:
        df = clean_column_names(df)
        result_df, _, msg = calculate_all_rows(df, target_irr, tax_rate, period_input, cost_maint_m, cost_admin_hh, cost_admin_m, margin_override)
        
        if msg: st.error(msg)
        else:
            st.subheader("📊 분석 결과 요약")
            view_cols = ["공사관리번호", "투자분석명", "용도", "연간판매량", "최소경제성만족판매량", "달성률"]
            # 실제 존재하는 컬럼만 필터링하여 출력
            existing_cols = [c for c in result_df.columns if any(k in c for k in view_cols)]
            st.dataframe(result_df[existing_cols].style.format({"달성률": "{:.1f}%", "최소경제성만족판매량": "{:,.0f}"}))
            
            # 그래프 및 누적 분석 (원본 코드의 Visual Analytics 로직)
            col_id = find_col(result_df, ["공사관리번호", "관리번호"])
            if col_id:
                chart_df = result_df.copy()
                chart_df['년도'] = chart_df[col_id].astype(str).str[:4]
                chart_df = chart_df[chart_df['년도'].str.isnumeric()]
                chart_df['년도'] = chart_df['년도'].astype(int)
                
                st.divider()
                st.header("📉 시각화 리포트")
                annual_sum = chart_df.groupby('년도')['최소경제성만족판매량'].sum()
                st.bar_chart(annual_sum, color="#FF6C6C")

# --------------------------------------------------------------------------
# [모드 2] 신규배관 경제성 분석 Simulation (개별 시뮬레이션)
# --------------------------------------------------------------------------
else:
    st.title("🏗️ 신규배관 경제성 분석 Simulation")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 투자 정보")
        sim_len = st.number_input("투자 길이 (m)", value=7000.0)
        sim_inv = st.number_input("총 공사비 (원)", value=7000000000, format="%d")
        sim_contrib = st.number_input("시설 분담금 (원)", value=22048100, format="%d")
        sim_other = st.number_input("기타 이익 (보조금, 원)", value=7000000000, format="%d")
        sim_jeon = st.number_input("공급 전수 (전)", value=2)

    with col2:
        st.subheader("2. 수익 정보 (연간)")
        sim_vol = st.number_input("연간 판매량 (MJ)", value=13250280.0)
        sim_rev = st.number_input("연간 판매액 (매출, 원)", value=305103037)
        sim_cost = st.number_input("연간 판매원가 (원)", value=256160477)

    if st.button("🚀 경제성 분석 실행", type="primary"):
        # 로직 계산 (엑셀 동기화 방식)
        net_inv = sim_inv - sim_contrib - sim_other
        margin = sim_rev - sim_cost
        cost_sga = (sim_len * cost_maint) + (sim_len * cost_admin_m) + (sim_jeon * cost_admin_hh)
        dep = sim_inv / period_input
        ebit = margin - cost_sga - dep
        net_inc = ebit * (1 - tax_rate)
        ocf = net_inc + dep
        
        flows = [-net_inv] + [ocf] * int(period_input)
        npv = manual_npv(target_irr, flows)
        irr = manual_irr(flows)
        
        # 결과 표시
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("순현재가치 (NPV)", f"{npv:,.0f} 원")
        
        if irr is None:
            m2.metric("내부수익률 (IRR)", "계산 불가")
            st.caption(f"🚩 **사유**: 초기 투자비 0원 이하(자본 투입 없음) 또는 운영 적자 지속")
        else:
            m2.metric("내부수익률 (IRR)", f"{irr*100:.2f} %")
        m3.metric("할인회수기간 (DPP)", "회수 불가" if npv < 0 else "계산 필요")

        # 분석 사유 요약
        st.subheader("🧐 NPV 산출 사유 분석")
        st.markdown(f"""
        현재 NPV가 **{npv:,.0f}원**으로 산출된 주요 원인은 다음과 같습니다:
        
        1. **운영 수익성 결여**: 연간 매출 마진({margin:,.0f}원)보다 판관비 합계({cost_sga:,.0f}원)가 더 커서 본원적인 영업 적자 상태입니다.
        2. **감가상각 부담**: 총 공사비 70억 원에 대해 매년 **{dep:,.0f}원**의 감가상각비가 발생하여 비용 부담을 가중시키고 있습니다.
        3. **현금흐름 적자 지속**: 세금 절감 효과와 감가상각비 환입을 고려하더라도, 매년 **{ocf:,.0f}원**의 **세후 수요개발 기대이익(적자)**이 발생하고 있습니다.
        4. **미래 가치 누적**: 매년 발생하는 약 **{abs(ocf):,.0f}원**의 손실이 {period_input}년 동안 누적 및 할인되어 최종 NPV에 반영되었습니다.
        """)
        
        st.subheader("🔎 세부 계산 근거")
        st.info(f"**초기 순투자액(Year 0): {net_inv:,.0f} 원** | **세후 수요개발 기대이익(OCF): {ocf:,.0f} 원**")
        st.line_chart(np.cumsum(flows))
