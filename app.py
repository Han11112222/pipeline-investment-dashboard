import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --------------------------------------------------------------------------
# [설정 1] 파일명 및 공통 적용 상수 (User Setting)
# --------------------------------------------------------------------------
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# 1. 깃허브에 올린 파일명 (정확해야 함)
DEFAULT_FILE_NAME = "리스트_20260129.xlsx"

# 2. 공통 적용 변수 (엑셀에서 제외하고 일괄 적용)
CONST_TAX_CORP = 0.19       # 법인세 19.0%
CONST_TAX_RESIDENT = 0.019  # 주민세 1.9%
CONST_TAX_RATE = CONST_TAX_CORP + CONST_TAX_RESIDENT # 총 20.9%

CONST_PERIOD = 30           # 감가상각 30년

# 3. 비용 단가 (일괄 적용)
COST_MAINT_M = 8222         # 연간 배관유지비 (원/m)
COST_ADMIN_HH = 6209        # 연간 일반관리비 (원/전)
COST_ADMIN_M = 13605        # 연간 일반관리비 (원/m) - 산업용/업무용 등

# --------------------------------------------------------------------------
# [함수] 데이터 처리 헬퍼
# --------------------------------------------------------------------------
def find_col(df, keyword):
    """엑셀 컬럼명 스마트 검색 (공백 무시)"""
    for col in df.columns:
        if keyword in str(col).replace(" ", ""):
            return col
    return None

def parse_value(value):
    """숫자만 추출 (쉼표, 문자 제거)"""
    if pd.isna(value) or value == '':
        return 0.0
    clean_str = str(value).replace(',', '')
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

def clean_column_names(df):
    """컬럼명 공백 제거"""
    df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
    return df

# --------------------------------------------------------------------------
# [함수] 핵심 역산 로직 (Goal Seek)
# --------------------------------------------------------------------------
def calculate_min_volume(df, target_irr):
    
    # 1. 고정 변수 사용 (사이드바 입력 대신 코드 내 상수 사용)
    tax_rate = CONST_TAX_RATE
    period = CONST_PERIOD
    
    # 2. PVIFA (연금현가계수)
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 3. 컬럼 매칭 (비용 컬럼은 찾지 않음 -> 상수로 대체)
    col_invest = find_col(df, "투자금액")
    col_contrib = find_col(df, "시설분담금")
    col_vol = find_col(df, "연간판매량")
    col_profit = find_col(df, "연간판매수익")
    col_len = find_col(df, "길이")
    col_hh = find_col(df, "계획전수")

    # 진행바
    progress_bar = st.progress(0, text="공통 비용 인자 적용하여 역산 중...")
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # --- A. 기초 데이터 (엑셀에서 읽기) ---
            investment = parse_value(row.get(col_invest, 0))
            contribution = parse_value(row.get(col_contrib, 0))
            
            current_sales_volume = parse_value(row.get(col_vol, 0))
            current_sales_profit = parse_value(row.get(col_profit, 0))
            
            length = parse_value(row.get(col_len, 0))
            households = parse_value(row.get(col_hh, 0))

            # --- B. 비용 데이터 (코드 내 상수 사용 - 일괄적용) ---
            # 엑셀 값을 읽지 않고, 위에서 정의한 COST_ 변수를 바로 사용합니다.
            maint_cost_per_m = COST_MAINT_M
            admin_cost_per_hh = COST_ADMIN_HH
            admin_cost_per_m = COST_ADMIN_M

            # 예외처리
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- C. 역산 로직 (Calculation) ---
            
            # 1. 순투자액
            net_investment = investment - contribution
            
            # 2. 목표 OCF (자본회수 필요액)
            if net_investment <= 0:
                required_capital_recovery = 0
            else:
                required_capital_recovery = net_investment / pvifa

            # 3. 연간 총 판관비 (Total SG&A) - 일괄적용
            # [수정] 모든 항목을 합산 적용 (세대수 없으면 0이 됨)
            total_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            
            # 4. 감가상각비
            depreciation = investment / period

            # 5. 필요 세전 영업이익 (Required EBIT)
            required_ebit = (required_capital_recovery - depreciation) / (1 - tax_rate)

            # 6. 필요 공헌이익 (Gross Margin)
            required_gross_margin = required_ebit + total_sga + depreciation

            # 7. 단위당 마진
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # 8. 최종 목표 판매량
            required_volume = required_gross_margin / unit_margin
            
            results.append(max(0, round(required_volume, 2)))

        except Exception:
            results.append(0)
        
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    
    # 달성률
    df['달성률(%)'] = df.apply(lambda x: round((x[col_vol] / x['최소경제성만족판매량'] * 100), 1) if x['최소경제성만족판매량'] > 0 and col_vol else 999.9, axis=1)

    return df

# --------------------------------------------------------------------------
# [UI 구성] 사이드바
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 데이터 파일")
    data_source = st.radio("파일 소스", ("GitHub 기본 파일", "엑셀 업로드"), index=0)
    
    uploaded_file = None
    if data_source == "엑셀 업로드":
        uploaded_file = st.file_uploader("파일 선택 (.xlsx)", type=['xlsx'])
    
    st.divider()
    
    st.subheader("⚙️ 분석 기준 (IRR)")
    target_irr = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
    
    st.divider()
    st.info(f"""
    **[일괄 적용된 기준]**
    * 법인세+주민세: {CONST_TAX_RATE*100:.1f}%
    * 감가상각: {CONST_PERIOD}년
    * 배관유지비: {COST_MAINT_M:,}원/m
    * 일반관리비(전): {COST_ADMIN_HH:,}원/전
    * 일반관리비(m): {COST_ADMIN_M:,}원/m
    """)

# --------------------------------------------------------------------------
# [UI 구성] 메인 화면
# --------------------------------------------------------------------------
st.title("💰 도시가스 배관투자 경제성 분석기")
st.markdown(f"""
**[분석 개요]**
* **목표:** 기존 투자 건에 대해 **IRR 6.15%**를 달성하기 위한 **'최소경제성만족판매량'** 산출
* **특이사항:** 비용 및 세금 항목은 엑셀값이 아닌 **공통 기준(일괄적용)**을 사용하여 분석함.
* **적용파일:** `{DEFAULT_FILE_NAME}`
""")
st.divider()

# 데이터 로드
df = None

if data_source == "GitHub 기본 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
            st.success(f"✅ 기본 파일 '{DEFAULT_FILE_NAME}' 로드 완료")
        except Exception as e:
            st.error(f"❌ 파일 읽기 실패: {e}")
    else:
        st.warning(f"⚠️ '{DEFAULT_FILE_NAME}' 파일이 없습니다.")
        
elif data_source == "엑셀 업로드" and uploaded_file:
    df = pd.read_excel(uploaded_file, engine='openpyxl')
    st.success("✅ 업로드 파일 로드 완료")

# 결과 처리
if df is not None:
    df = clean_column_names(df)
    result_df = calculate_min_volume(df, target_irr)
    
    st.subheader("📊 분석 결과: 최소경제성만족판매량")
    
    # 표시할 컬럼 찾기
    key_cols = ["공사관리번호", "투자분석명", "용도", "연간판매량", "최소경제성만족판매량", "달성률"]
    display_cols = []
    for k in key_cols:
        found = find_col(result_df, k)
        if found:
            display_cols.append(found)
            
    # 결과표 출력
    if display_cols:
        st.dataframe(
            result_df[display_cols].style.background_gradient(subset=[find_col(result_df, "최소경제성만족판매량")], cmap="Oranges"),
            use_container_width=True
        )

    # 엑셀 다운로드
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 18)
        
    st.download_button(
        label="📥 결과 엑셀 다운로드 (Click)",
        data=output.getvalue(),
        file_name="최소경제성만족판매량_분석결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
