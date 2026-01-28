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
# [함수] 데이터 전처리 & 파싱
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
# [함수] 엑셀 동일 로직 (단순 연 단위 계산)
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m, margin_override=None):
    # 1. PVIFA (연금현가계수)
    # 엑셀의 [년도별 손익 계산]과 동일하게 "기말불 연금(Ordinary Annuity)" 공식 적용
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    margin_debug = [] 
    
    # 컬럼 매칭
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
            # 데이터 로드
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

            # [Step 1] 순투자액 (Net Investment)
            # 엑셀: 투자비 - 분담금 (0년차 현금유출)
            net_investment = investment - contribution
            
            # [Step 2] 목표 연간 회수액 (Required Annual OCF)
            # 엑셀: 30년 동안 일정하게 회수해야 하는 세후 현금흐름
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # [Step 3] 판관비 (비용)
            maint_cost = length * cost_maint_m
            if any(k in str(usage_str) for k in ['공동', '단독', '주택', '아파트']):
                admin_cost = households * cost_admin_hh
            else:
                admin_cost = length * cost_admin_m
            total_sga = maint_cost + admin_cost
            
            # [Step 4] 감가상각비 & 세전이익 역산
            # 엑셀: (17)투자비 ÷ 30년
            depreciation = investment / period
            
            # 공식: OCF = (EBIT * (1-t)) + Dep
            # 변형: EBIT = (OCF - Dep) / (1-t)
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)
            
            # [Step 5] 필요 마진총액 (Gross Margin)
            # 마진 = EBIT + 판관비 + 감가상각비
            required_gross_margin = required_ebit + total_sga + depreciation
            
            # [Step 6] 마진 단가 결정 (수동/자동)
            calculated_margin = current_profit / current_vol
            if margin_override and margin_override > 0:
                final_margin = margin_override
            else:
                final_margin = calculated_margin

            if final_margin <= 0:
                results.append(0)
                margin_debug.append(0)
                continue

            # [Step 7] 최종 목표 판매량
            required_volume = required_gross_margin / final_margin
            results.append(max(0, required_volume))
            margin_debug.append(final_margin)

        except:
            results.append(0)
            margin_debug.append(0)
    
    df['최소경제성만족판매량'] = results
    df['적용마진(원)'] = margin_debug
    
    # 달성률 계산 (소수점 1자리 표시용 데이터는 나중에 포맷팅)
    df['달성률'] = df.apply(
        lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), 
        axis=1
    )

    return df, results, None

# --------------------------------------------------------------------------
# [UI] 사이드바
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 설정")
    data_source = st.radio("소스", ("GitHub 파일", "엑셀 업로드"))
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
    
    st.divider()
    st.subheader("⚙️ 분석 기준")
    # [설정] 엑셀과 동일한 입력을 위해 정밀도 제공
    target_irr_percent = st.number_input("목표 IRR (%)", value=6.1500, format="%.4f", step=0.0001)
    tax_rate_percent = st.number_input("세율 (%)", value=20.9, format="%.1f", step=0.1)
    period_input = st.number_input("상각 기간 (년)", value=30, step=1)
    
    st.subheader("💰 비용 단가 (2024년 기준)")
    cost_maint_m_input = st.number_input("유지비 (원/m)", value=8222)
    cost_admin_hh_input = st.number_input("관리비 (원/전)", value=6209)
    cost_admin_m_input = st.number_input("관리비 (원/m)", value=13605)

    st.divider()
    st.subheader("🔧 정밀 보정")
    margin_override_input = st.number_input("단위당 마진 강제 (원/MJ)", value=0.0, step=0.0001, format="%.4f")
    st.caption("* 0이면 자동 계산 (추천)")

    target_irr = target_irr_percent / 100
    tax_rate = tax_rate_percent / 100

# --------------------------------------------------------------------------
# [UI] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")
st.markdown("💡 **엑셀 기준(Year 0 투자 → Year 1~30 회수) 단순 연금 모델 적용**")

# 상단 요약
c1, c2, c3, c4 = st.columns(4)
c1.metric("목표 IRR", f"{target_irr_percent:.4f}%")
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
        
        # [핵심] 화면 표시는 깔끔하게 (소수점 1자리)
        try:
            styler = final_df.style
            if "최소경제성만족판매량(MJ)" in final_df.columns:
                styler = styler.background_gradient(subset=["최소경제성만족판매량(MJ)"], cmap="Oranges")
            
            format_dict = {
                "현재판매량(MJ)": "{:,.0f}",
                "최소경제성만족판매량(MJ)": "{:,.1f}", # 요청하신 1자리
                "달성률": "{:.1f}%",                 # 요청하신 1자리
                "적용마진(원/MJ)": "{:.4f}"            # 마진은 정밀하게 확인
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
        # 상세 산출 근거 (엑셀 대조용)
        # ------------------------------------------------------------------
        st.divider()
        st.subheader("🧮 산출 근거 상세 (Excel Logic Check)")
        
        name_col = find_col(result_df, ["투자분석명", "공사명"])
        if name_col:
            selected = st.selectbox("프로젝트 선택:", result_df[name_col].unique())
            row = result_df[result_df[name_col] == selected].iloc[0]
            
            # 데이터 추출
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

            # 재계산 (엑셀 로직)
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
            
            auto_margin = profit / vol if vol > 0 else 0
            if margin_override_input > 0:
                final_margin = margin_override_input
            else:
                final_margin = auto_margin

            final_vol = req_gross / final_margin if final_margin > 0 else 0

            # 2단 표시
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**1. 투자 정보**")
                st.write(f"- 순투자액: **{net_inv:,.0f}** 원")
                st.write(f"- 운영 비용: {total_sga:,.0f} 원")
            with c2:
                st.markdown("**2. 수익 구조**")
                st.info(f"👉 **적용 마진:** {final_margin:.4f} 원/MJ")

            st.markdown("---")
            if final_vol > 0:
                verify_margin = final_vol * final_margin
                verify_ocf = (verify_margin - total_sga - dep) * (1 - tax_rate) + dep
                verify_npv = (verify_ocf * pvifa) - net_inv
                
                st.write(f"**[최종 결과]** 목표 달성 최소 판매량: **{final_vol:,.1f} MJ**")
                
                # NPV 검증
                if abs(verify_npv) < 1000:
                    st.success("✅ 엑셀식 NPV 검증 완료 (Year 0 지출, Year 1~30 균등 회수)")
                else:
                    st.warning("⚠️ 미세 오차 발생")
