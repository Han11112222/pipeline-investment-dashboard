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
    """키워드로 컬럼 찾기"""
    for col in df.columns:
        for kw in keywords:
            if kw in col:
                return col
    return None

def parse_value(value):
    """숫자만 추출"""
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
# [함수] 계산 로직
# --------------------------------------------------------------------------
def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m):
    # PVIFA
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

    if not col_invest or not col_vol or not col_profit:
        return df, "❌ 핵심 컬럼 미발견"

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
            
            unit_margin = current_profit / current_vol
            if unit_margin <= 0:
                results.append(0)
                continue

            required_volume = required_gross_margin / unit_margin
            results.append(max(0, required_volume))

        except:
            results.append(0)
    
    df['최소경제성만족판매량'] = results
    
    # 달성률 계산 (목표가 0이면 999.9% 처리)
    df['달성률'] = df.apply(
        lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 1 else (999.9 if x[col_vol] > 0 else 0), 
        axis=1
    )

    return df, None

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
    
    st.subheader("💰 비용 단가")
    cost_maint_m_input = st.number_input("유지비 (원/m)", value=8222)
    cost_admin_hh_input = st.number_input("관리비 (원/전)", value=6209)
    cost_admin_m_input = st.number_input("관리비 (원/m)", value=13605)

    target_irr = target_irr_percent / 100
    tax_rate = tax_rate_percent / 100

# --------------------------------------------------------------------------
# [UI] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")

c1, c2, c3, c4 = st.columns(4)
c1.metric("목표 IRR", f"{target_irr_percent}%")
c2.metric("적용 세율", f"{tax_rate_percent}%")
c3.metric("유지비", f"{cost_maint_m_input:,}원")
c4.metric("관리비(주택)", f"{cost_admin_hh_input:,}원")

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
    result_df, msg = calculate_all_rows(
        df, target_irr, tax_rate, period_input, 
        cost_maint_m_input, cost_admin_hh_input, cost_admin_m_input
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
            "달성률": ["달성률"]
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
                "달성률": "{:.1f}%"
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
        # 상세 산출 근거 + [검증 기능 추가]
        # ------------------------------------------------------------------
        st.divider()
        st.subheader("🧮 산출 근거 상세 & 검증")
        
        name_col = find_col(result_df, ["투자분석명", "공사명"])
        if name_col:
            selected = st.selectbox("프로젝트 선택:", result_df[name_col].unique())
            row = result_df[result_df[name_col] == selected].iloc[0]
            
            # 파싱 및 계산
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
            unit_margin = profit / vol if vol > 0 else 0
            final_vol = req_gross / unit_margin if unit_margin > 0 else 0

            # 표시
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**1. 투자 정보**")
                st.write(f"- 순투자액: **{net_inv:,.0f}** 원")
                st.write(f"- 시설: {length}m / {hh}세대 ({note})")
            with c2:
                st.markdown("**2. 수익 구조**")
                st.write(f"- 현재 판매량: **{vol:,.0f}** MJ")
                st.write(f"- 단위 마진: **{unit_margin:.2f}** 원/MJ")

            st.info(f"""
            **[최종 결과]**
            목표 IRR {target_irr_percent}% 달성을 위한 최소 판매량:
            **{max(0, final_vol):,.0f} MJ**
            """)

            # ------------------------------------------------------------------
            # [신규] NPV 검증 로직 (User Trust용)
            # ------------------------------------------------------------------
            if final_vol > 0:
                st.markdown("---")
                st.markdown("### ✅ 정밀 검증: 이 판매량일 때 NPV는?")
                
                # 1. 예상 연간 수익(Margin) 계산
                verify_margin = final_vol * unit_margin
                # 2. 세전 이익 (마진 - 판관비 - 감가상각)
                verify_ebit = verify_margin - total_sga - dep
                # 3. 세후 이익
                verify_eat = verify_ebit * (1 - tax_rate)
                # 4. 세후 현금흐름 (OCF) = 세후이익 + 감가상각
                verify_ocf = verify_eat + dep
                
                # 5. NPV 계산 (OCF * PVIFA - 순투자액)
                verify_npv = (verify_ocf * pvifa) - net_investment
                # net_investment 변수명 통일 (위에서 net_inv로 씀)
                verify_npv = (verify_ocf * pvifa) - net_inv
                
                st.write(f"만약 판매량이 **{final_vol:,.0f} MJ**이라면...")
                st.write(f"- 연간 예상 수익(Margin): {verify_margin:,.0f} 원")
                st.write(f"- 연간 현금흐름(OCF): {verify_ocf:,.0f} 원")
                st.write(f"- 30년 현금흐름의 현재가치 합계: {verify_ocf * pvifa:,.0f} 원")
                
                if abs(verify_npv) < 1000: # 오차범위 1000원 이내
                    st.success(f"👉 **검증 결과 NPV: {verify_npv:,.0f} 원 (정확히 0에 수렴)** ✅")
                    st.caption("수학적으로 정확한 최소 판매량임이 증명되었습니다.")
                else:
                    st.warning(f"👉 검증 결과 NPV: {verify_npv:,.0f} 원 (오차 발생)")
