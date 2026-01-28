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
# [함수] 데이터 전처리
# --------------------------------------------------------------------------
def clean_column_names(df):
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
# [함수] 역산 로직 (마진 보정 기능 추가)
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m, margin_override=None):
    # PVIFA
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    margin_debug = [] # 디버깅용
    
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

            maint_cost = length * cost_maint_m
            if any(k in str(usage_str) for k in ['공동', '단독', '주택', '아파트']):
                admin_cost = households * cost_admin_hh
            else:
                admin_cost = length * cost_admin_m
            total_sga = maint_cost + admin_cost
            
            depreciation = investment / period
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)
            required_gross_margin = required_ebit + total_sga + depreciation
            
            # [핵심] 단위당 마진 계산
            calculated_margin = current_profit / current_vol
            
            # 사용자가 강제 보정값을 입력했으면 그것을 사용 (0이 아닐 때)
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
    df['적용마진(원)'] = margin_debug # 확인용 컬럼
    
    df['달성률'] = df.apply(
        lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), 
        axis=1
    )

    return df, results, None

# --------------------------------------------------------------------------
# [UI] 사이드바
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 파일 및 설정")
    data_source = st.radio("소스 선택", ("GitHub 파일", "엑셀 업로드"))
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
    
    st.divider()
    st.subheader("⚙️ 분석 기준")
    target_irr_percent = st.number_input("목표 IRR (%)", value=6.15, format="%.2f", step=0.01)
    tax_rate_percent = st.number_input("세율 (%)", value=20.9, format="%.1f", step=0.1)
    period_input = st.number_input("상각 기간 (년)", value=30, step=1)
    
    st.subheader("💰 비용 단가 (2024년 기준)")
    cost_maint_m_input = st.number_input("유지비 (원/m)", value=8222)
    cost_admin_hh_input = st.number_input("관리비 (원/전)", value=6209)
    cost_admin_m_input = st.number_input("관리비 (원/m)", value=13605)

    st.divider()
    st.subheader("🔧 정밀 보정 (Optional)")
    st.caption("엑셀과 값이 다를 때, 단위 마진을 직접 입력해보세요.")
    margin_override_input = st.number_input("단위당 마진 강제 적용 (원/MJ)", value=0.0, step=0.01, format="%.4f")
    st.caption("* 0으로 두면 파일에 있는 '수익÷물량'으로 자동 계산합니다.")

    target_irr = target_irr_percent / 100
    tax_rate = tax_rate_percent / 100

# --------------------------------------------------------------------------
# [UI] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")

# 상단 요약
c1, c2, c3, c4 = st.columns(4)
c1.metric("목표 IRR", f"{target_irr_percent}%")
c2.metric("적용 세율", f"{tax_rate_percent}%")
c3.metric("유지비", f"{cost_maint_m_input:,}원")
c4.metric("적용 마진", f"{margin_override_input}원/MJ" if margin_override_input > 0 else "자동 계산")

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
    
    # 계산 실행 (마진 오버라이드 포함)
    result_df, margins, msg = calculate_all_rows(
        df, target_irr, tax_rate, period_input, 
        cost_maint_m_input, cost_admin_hh_input, cost_admin_m_input,
        margin_override_input
    )
    
    if msg:
        st.error(msg)
    else:
        st.divider()
        st.subheader("📊 분석 결과 요약")
        
        view_cols_map = {
            "공사관리번호": ["공사관리번호", "관리번호"],
            "투자분석명": ["투자분석명", "공사명"],
            "용도": ["용도"],
            "현재판매량(MJ)": ["연간판매량", "판매량계"],
            "최소경제성만족판매량(MJ)": ["최소경제성만족판매량"],
            "달성률": ["달성률"],
            "적용마진(원/MJ)": ["적용마진"]
        }
        
        final_df = pd.DataFrame()
        for label, keywords in view_cols_map.items():
            found = find_col(result_df, keywords)
            if found:
                final_df[label] = result_df[found]
        
        try:
            styler = final_df.style
            if "최소경제성만족판매량(MJ)" in final_df.columns:
                styler = styler.background_gradient(subset=["최소경제성만족판매량(MJ)"], cmap="Oranges")
            
            format_dict = {
                "현재판매량(MJ)": "{:,.0f}",
                "최소경제성만족판매량(MJ)": "{:,.0f}",
                "달성률": "{:.1f}%",
                "적용마진(원/MJ)": "{:.4f}"
            }
            valid_format = {k: v for k, v in format_dict.items() if k in final_df.columns}
            styler = styler.format(valid_format)

            st.dataframe(styler, use_container_width=True, hide_index=True)
        except:
            st.dataframe(final_df, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False)
            writer.sheets['Sheet1'].set_column('A:Z', 18)
        st.download_button("📥 엑셀 다운로드", output.getvalue(), "분석결과.xlsx", "primary")

        # ------------------------------------------------------------------
        # 산출 근거 상세
        # ------------------------------------------------------------------
        st.divider()
        st.subheader("🧮 산출 근거 상세 (검증)")
        
        name_col = find_col(result_df, ["투자분석명", "공사명"])
        if name_col:
            selected = st.selectbox("프로젝트 선택:", result_df[name_col].unique())
            row = result_df[result_df[name_col] == selected].iloc[0]
            
            # 파싱
            col_inv = find_col(result_df, ["배관투자"])
            col_cont = find_col(result_df, ["분담금"])
            col_vol = find_col(result_df, ["판매량계", "연간판매량"])
            col_prof = find_col(result_df, ["판매수익"])
            col_len = find_col(result_df, ["길이"])
            col_hh = find_col(result_df, ["계획전수"])
            col_use = find_col(result_df, ["용도"])

            inv = parse_value(row.get(col_inv))
            cont = parse_value(row.get(col_cont))
            vol = parse_value(row.get(col_vol))
            profit = parse_value(row.get(col_prof))
            length = parse_value(row.get(col_len))
            hh = parse_value(row.get(col_hh))
            usage = str(row.get(col_use, ""))

            # 계산 재연
            pvifa = (1 - (1 + target_irr) ** (-period_input)) / target_irr
            net_inv = inv - cont
            req_capital = max(0, net_inv / pvifa)
            
            maint_c = length * cost_maint_m_input
            if any(k in usage for k in ['공동', '단독', '주택', '아파트']):
                admin_c = hh * cost_admin_hh_input
                note = "주택용"
            else:
                admin_c = length * cost_admin_m_input
                note = "비주택"
            total_sga = maint_c + admin_c
            
            dep = inv / period_input
            req_ebit = (req_capital - dep) / (1 - tax_rate)
            req_gross = req_ebit + total_sga + dep
            
            # 마진 결정 (자동 vs 수동)
            auto_margin = profit / vol if vol > 0 else 0
            if margin_override_input > 0:
                final_margin = margin_override_input
                margin_source = "수동 입력값"
            else:
                final_margin = auto_margin
                margin_source = "자동 계산값 (수익÷물량)"

            final_vol = req_gross / final_margin if final_margin > 0 else 0

            # 상세 화면
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**1. 투자 정보**")
                st.write(f"- 순투자액: **{net_inv:,.0f}** 원")
                st.write(f"- 적용 비용: {total_sga:,.0f} 원 ({note})")
            with c2:
                st.markdown("**2. 수익 구조**")
                st.write(f"- 엑셀 판매수익: {profit:,.0f} 원")
                st.write(f"- 엑셀 판매량: {vol:,.0f} MJ")
                st.info(f"👉 **적용 마진:** {final_margin:.4f} 원/MJ ({margin_source})")

            # 검증 로직
            if final_vol > 0:
                verify_margin = final_vol * final_margin
                verify_ocf = (verify_margin - total_sga - dep) * (1 - tax_rate) + dep
                verify_npv = (verify_ocf * pvifa) - net_inv
                
                st.markdown("---")
                st.markdown(f"**[검증 결과] 판매량이 {final_vol:,.0f} MJ 일 때...**")
                
                

                st.write(f"- 필요 OCF: {req_capital:,.0f} 원 (vs 검증 OCF: {verify_ocf:,.0f} 원)")
                if abs(verify_npv) < 1000:
                    st.success(f"✅ NPV = {verify_npv:,.0f} 원 (정확히 일치)")
                else:
                    st.warning(f"⚠️ NPV = {verify_npv:,.0f} 원 (오차 발생 - 마진 단가를 미세 조정해보세요)")
