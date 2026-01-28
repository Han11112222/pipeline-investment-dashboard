import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정] 페이지 기본 설정
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# --------------------------------------------------------------------------
# [함수] 데이터 전처리
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
# [함수] 판관비 및 메인 계산 로직 (동적 변수 적용)
# --------------------------------------------------------------------------
def calculate_sga(usage_str, length, households, cost_maint_m, cost_admin_hh, cost_admin_m):
    """용도별 판관비 계산"""
    maint_cost = length * cost_maint_m
    usage = str(usage_str).strip()
    
    if any(k in usage for k in ['공동', '단독', '주택', '아파트', '주거', '다세대']):
        admin_cost = households * cost_admin_hh
    else:
        admin_cost = length * cost_admin_m
        
    return maint_cost + admin_cost

def calculate_all_rows(df, target_irr, tax_rate, period, cost_maint_m, cost_admin_hh, cost_admin_m):
    # PVIFA
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 컬럼 매칭
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

            # 역산 로직
            net_investment = investment - contribution
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # 판관비 (동적 변수 전달)
            total_sga = calculate_sga(usage_str, length, households, cost_maint_m, cost_admin_hh, cost_admin_m)
            
            depreciation = investment / period
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)
            required_gross_margin = required_ebit + total_sga + depreciation
            
            unit_margin = current_profit / current_vol
            if unit_margin <= 0:
                results.append(0)
                continue

            required_volume = required_gross_margin / unit_margin
            results.append(max(0, round(required_volume, 2)))

        except:
            results.append(0)
    
    df['최소경제성만족판매량'] = results
    df['달성률'] = df.apply(lambda x: (x[col_vol] / x['최소경제성만족판매량'] * 100) if x['최소경제성만족판매량'] > 0 else 999.9, axis=1)

    return df, None

# --------------------------------------------------------------------------
# [UI 구성] 사이드바 (입력 제어)
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 파일 및 설정")
    data_source = st.radio("소스 선택", ("GitHub 파일", "엑셀 업로드"))
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 업로드", type=['xlsx'])
    
    st.divider()
    
    st.subheader("⚙️ 분석 기준 설정 (수정 가능)")
    
    # [수정 가능한 입력창]
    target_irr_percent = st.number_input("목표 IRR (%)", value=6.15, format="%.2f", step=0.01)
    tax_rate_percent = st.number_input("세율 (법인세+주민세 %)", value=20.9, format="%.1f", step=0.1)
    period_input = st.number_input("감가상각 기간 (년)", value=30, step=1)
    
    st.divider()
    st.subheader("💰 비용 단가 설정")
    cost_maint_m_input = st.number_input("배관유지비 (원/m)", value=8222)
    cost_admin_hh_input = st.number_input("일반관리비 (원/전, 주택)", value=6209)
    cost_admin_m_input = st.number_input("일반관리비 (원/m, 기타)", value=13605)

    # 실제 계산에 쓸 변수 변환
    target_irr = target_irr_percent / 100
    tax_rate = tax_rate_percent / 100

# --------------------------------------------------------------------------
# [UI 구성] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")

# 상단 분석 기준 표시 (가독성 향상)
c1, c2, c3, c4 = st.columns(4)
c1.metric("목표 IRR", f"{target_irr_percent}%")
c2.metric("적용 세율", f"{tax_rate_percent}%")
c3.metric("상각 기간", f"{period_input}년")
c4.metric("분석 대상", "2020~2024 투자건")

# 데이터 로드
df = None
if data_source == "GitHub 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
    else:
        st.warning(f"⚠️ {DEFAULT_FILE_NAME} 파일 없음")
elif data_source == "엑셀 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')

# 결과 출력
if df is not None:
    df = clean_column_names(df)
    
    # 계산 실행 (사이드바 입력값 전달)
    result_df, msg = calculate_all_rows(
        df, target_irr, tax_rate, period_input, 
        cost_maint_m_input, cost_admin_hh_input, cost_admin_m_input
    )
    
    if msg:
        st.error(msg)
    else:
        st.divider()
        st.subheader("📊 분석 결과 요약")
        
        # 1. 보여줄 컬럼 선택
        view_cols_map = {
            "공사관리번호": "공사관리번호",
            "투자분석명": "투자분석명", 
            "용도": "용도",
            "연간판매량": "현재판매량(MJ)", # 표시 이름 변경
            "최소경제성만족판매량": "목표판매량(MJ)", # 표시 이름 변경
            "달성률": "달성률(%)"
        }
        
        # 실제 데이터프레임 컬럼 매칭
        final_df = pd.DataFrame()
        for key, label in view_cols_map.items():
            found = find_col(result_df, [key, "판매량계"]) # 판매량계 등 별칭 처리
            if found:
                final_df[label] = result_df[found]
        
        # 2. 테이블 출력 (포맷팅 적용)
        # st.column_config를 사용하여 천단위 콤마 및 소수점 제어
        st.dataframe(
            final_df,
            column_config={
                "현재판매량(MJ)": st.column_config.NumberColumn(format="%,.0f"), # 천단위 콤마
                "목표판매량(MJ)": st.column_config.NumberColumn(format="%,.0f"), # 천단위 콤마
                "달성률(%)": st.column_config.NumberColumn(format="%.1f%%"),   # 소수점 1자리 + %
            },
            use_container_width=True,
            hide_index=True
        )

        # 엑셀 다운로드
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False)
            writer.sheets['Sheet1'].set_column('A:Z', 18)
        st.download_button("📥 전체 결과 엑셀 다운로드", output.getvalue(), "분석결과.xlsx", "primary")

        # ------------------------------------------------------------------
        # 상세 산출 근거 (업데이트된 변수 적용)
        # ------------------------------------------------------------------
        st.divider()
        st.subheader("🧮 산출 근거 상세 (Calculation Breakdown)")
        
        name_col = find_col(result_df, ["투자분석명", "공사명"])
        if name_col:
            project_list = result_df[name_col].unique()
            selected_project = st.selectbox("프로젝트 선택:", project_list)
            
            row = result_df[result_df[name_col] == selected_project].iloc[0]
            
            # 변수 추출
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

            # 재계산 (화면 표시용)
            pvifa = (1 - (1 + target_irr) ** (-period_input)) / target_irr
            net_inv = inv - cont
            req_capital = max(0, net_inv / pvifa)
            
            maint_c = length * cost_maint_m_input
            if any(k in usage for k in ['공동', '단독', '주택', '아파트']):
                admin_c = hh * cost_admin_hh_input
                admin_note = f"주택용({hh}전 × {cost_admin_hh_input:,})"
            else:
                admin_c = length * cost_admin_m_input
                admin_note = f"비주택({length}m × {cost_admin_m_input:,})"
            total_sga = maint_c + admin_c
            
            dep = inv / period_input
            req_ebit = (req_capital - dep) / (1 - tax_rate)
            req_gross = req_ebit + total_sga + dep
            unit_margin = profit / vol if vol > 0 else 0
            final_vol = req_gross / unit_margin if unit_margin > 0 else 0

            # 2단 레이아웃
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**1. 투자 및 시설 정보**")
                st.write(f"- 순투자액: **{net_inv:,.0f}** 원 (투자 {inv:,.0f} - 분담금 {cont:,.0f})")
                st.write(f"- 시설규모: 길이 **{length}m**, 세대수 **{hh}전**")
            with col2:
                st.markdown("**2. 수익 구조**")
                st.write(f"- 현재 판매량: **{vol:,.0f}** MJ")
                st.write(f"- 단위 마진: **{unit_margin:.2f}** 원/MJ")

            st.markdown("---")
            st.markdown(f"**Step 1. 자본회수 필요액 (IRR {target_irr_percent}%)**")
            st.latex(f"\\frac{{{net_inv:,.0f}}}{{PVIFA}} = \\mathbf{{{req_capital:,.0f}}}")
            
            st.markdown(f"**Step 2. 연간 운영비 (판관비)**")
            st.caption(f"유지비({length}×{cost_maint_m_input:,}) + 관리비[{admin_note}]")
            st.write(f"= **{total_sga:,.0f}** 원")
            
            st.markdown(f"**Step 3. 필요 세전이익 (법인세 {tax_rate_percent}%)**")
            st.latex(f"\\frac{{(\\text{{자본회수}} {req_capital:,.0f} - \\text{{상각}} {dep:,.0f})}}{{1 - {tax_rate:.3f}}} = \\mathbf{{{req_ebit:,.0f}}}")

            st.markdown(f"**Step 4. 최종 목표 판매량**")
            st.info(f"필요마진({req_gross:,.0f}) ÷ 단위마진({unit_margin:.2f}) = **{max(0, final_vol):,.0f} MJ**")
