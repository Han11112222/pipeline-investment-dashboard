import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="도시가스 경제성 분석기", layout="wide")

# [설정] 깃허브에 올린 엑셀 파일 이름 (정확해야 합니다!)
DEFAULT_FILE_NAME = "리스트_20260128.xlsx"

# --- [함수] 데이터 전처리 (에러 방지용) ---

def clean_column_names(df):
    """
    컬럼명의 모든 공백을 제거합니다. 
    예: '배관투자금액  (원) ' -> '배관투자금액(원)'
    """
    df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
    return df

def find_col(df, keyword):
    """
    키워드가 포함된 컬럼명을 자동으로 찾습니다.
    (예: '투자금액'만 입력해도 '배관투자금액(원)'을 찾아냄)
    """
    for col in df.columns:
        if keyword in col:
            return col
    return None

def parse_cost_string(value):
    """
    '8,222원/(m,연)' 같은 텍스트에서 숫자만 추출합니다.
    """
    if pd.isna(value) or value == '':
        return 0.0
    # 쉼표 제거 및 문자열 변환
    clean_str = str(value).replace(',', '')
    # 숫자와 소수점(.)만 남기고 모두 제거
    numbers = re.findall(r"[\d\.]+", clean_str)
    if numbers:
        return float(numbers[0])
    return 0.0

# --- [함수] 핵심 역산 로직 ---
def calculate_target_volume(df, target_irr, tax_rate, period):
    
    # PVIFA (연금현가계수)
    if target_irr == 0:
        pvifa = period
    else:
        pvifa = (1 - (1 + target_irr) ** (-period)) / target_irr

    results = []
    
    # 컬럼 자동 매칭 (이게 핵심!)
    col_invest = find_col(df, "배관투자금액")
    col_contrib = find_col(df, "시설분담금")
    col_vol = find_col(df, "연간판매량")
    col_profit = find_col(df, "연간판매수익") # 또는 '마진'
    col_len = find_col(df, "길이")
    col_hh = find_col(df, "계획전수") # 또는 '세대수'
    
    # 판관비 컬럼 찾기
    col_maint = find_col(df, "배관유지비")
    col_admin_hh = find_col(df, "일반관리비(전)")
    col_admin_m = find_col(df, "일반관리비(m)")

    # 진행바
    progress_bar = st.progress(0, text="경제성 역산 시뮬레이션 중...")
    total_rows = len(df)

    for index, row in df.iterrows():
        try:
            # 1. 데이터 추출 (컬럼을 못 찾으면 0 처리)
            investment = float(str(row.get(col_invest, 0)).replace(',', '')) if col_invest else 0
            contribution = float(str(row.get(col_contrib, 0)).replace(',', '')) if col_contrib else 0
            
            # 순투자액
            net_investment = investment - contribution

            # 현재 실적
            current_sales_volume = float(str(row.get(col_vol, 0)).replace(',', '')) if col_vol else 0
            current_sales_profit = float(str(row.get(col_profit, 0)).replace(',', '')) if col_profit else 0
            
            # 시설 현황
            length = float(str(row.get(col_len, 0)).replace(',', '')) if col_len else 0
            households = float(str(row.get(col_hh, 0)).replace(',', '')) if col_hh else 0

            # 판관비 (문자열 파싱 적용)
            maint_cost_per_m = parse_cost_string(row.get(col_maint, 0)) if col_maint else 0
            admin_cost_per_hh = parse_cost_string(row.get(col_admin_hh, 0)) if col_admin_hh else 0
            admin_cost_per_m = parse_cost_string(row.get(col_admin_m, 0)) if col_admin_m else 0

            # --- 예외 처리 ---
            if current_sales_volume <= 0 or investment <= 0:
                results.append(0)
                continue

            # --- 2. 역산 로직 (Goal Seek) ---
            
            # Step A. 목표 OCF (순투자액 회수용)
            if net_investment <= 0:
                required_ocf = 0 # 이미 분담금으로 회수됨
            else:
                required_ocf = net_investment / pvifa

            # Step B. 총 판관비 (운영비용)
            total_sga = (length * maint_cost_per_m) + (households * admin_cost_per_hh) + (length * admin_cost_per_m)
            
            # Step C. 감가상각비
            depreciation = investment / period

            # Step D. 필요 세전이익 (법인세 효과 고려)
            # OCF = (EBIT * (1-t)) + Dep  => EBIT = (OCF - Dep)/(1-t)
            required_pretax_profit = (required_ocf - depreciation) / (1 - tax_rate)

            # Step E. 필요 공헌이익 (Gross Margin)
            # 공헌이익 = 세전이익 + 판관비 + 감가상각비
            required_gross_margin = required_pretax_profit + total_sga + depreciation

            # Step F. 단위당 마진 (MJ당 수익)
            unit_margin = current_sales_profit / current_sales_volume
            
            if unit_margin <= 0:
                results.append(0)
                continue

            # Step G. 최종 목표 판매량
            required_volume = required_gross_margin / unit_margin
            
            # 결과가 음수면 0 처리 (이미 초과 달성)
            results.append(max(0, round(required_volume, 2)))

        except Exception:
            results.append(0)
        
        # 진행률 업데이트
        if index % 10 == 0:
            progress_bar.progress(min((index + 1) / total_rows, 1.0))

    progress_bar.progress(1.0)
    df['최소경제성만족판매량'] = results
    
    # 달성률 계산
    df['달성률(%)'] = df.apply(lambda x: round((x[col_vol] / x['최소경제성만족판매량'] * 100), 1) if x['최소경제성만족판매량'] > 0 and col_vol else 999.9, axis=1)
    
    return df

# =========================================================
# [UI 구성] 사이드바 (설정)
# =========================================================
with st.sidebar:
    st.header("📂 데이터 파일 선택")
    data_source = st.radio(
        "어떤 파일을 사용할까요?",
        ("GitHub 기본 파일", "엑셀 직접 업로드"),
        index=0
    )
    
    uploaded_file = None
    if data_source == "엑셀 직접 업로드":
        uploaded_file = st.file_uploader("파일 선택 (.xlsx)", type=['xlsx'])
    
    st.divider()
    st.subheader("⚙️ 분석 기준 (IRR 6.15%)")
    target_irr = st.number_input("목표 IRR (%)", value=6.15, format="%.2f") / 100
    tax_rate = st.number_input("세율 (법인세+주민세, %)", value=20.9, format="%.1f") / 100
    period = st.number_input("상각 기간 (년)", value=30)

# =========================================================
# [UI 구성] 메인 화면
# =========================================================
st.title("💰 도시가스 배관투자 경제성 역산 분석기")

st.markdown("""
### 📝 분석 개요
이 웹앱은 **기존 투자 구간(2020~2024)**의 투자 효율성을 검증하기 위해 제작되었습니다.
* **핵심 목표:** 회사 기준 IRR 6.15%를 달성하기 위한 **'최소경제성만족판매량'**을 역산(Goal Seek)합니다.
* **계산 방식:** 순투자액, 30년 감가상각, 법인세 효과(20.9%), 연간 판관비(유지비+일반관리비) 등 **모든 비용 인자를 반영**하여 정밀하게 계산합니다.
""")
st.divider()

# --- 데이터 로드 ---
df = None

if data_source == "GitHub 기본 파일":
    if os.path.exists(DEFAULT_FILE_NAME):
        try:
            # engine='openpyxl' 명시하여 에러 방지
            df = pd.read_excel(DEFAULT_FILE_NAME, engine='openpyxl')
            st.success(f"✅ 깃허브 파일 '{DEFAULT_FILE_NAME}'을 성공적으로 불러왔습니다.")
        except Exception as e:
            st.error(f"❌ 파일 읽기 실패: {e}\n(파일이 엑셀 형식이 맞는지 확인해주세요)")
    else:
        st.warning(f"⚠️ '{DEFAULT_FILE_NAME}' 파일이 없습니다. 깃허브에 파일이 있는지 확인해주세요.")
        
elif data_source == "엑셀 직접 업로드":
    if uploaded_file:
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        st.success("✅ 파일 업로드 완료!")

# --- 결과 처리 ---
if df is not None:
    # 1. 컬럼명 공백 제거 (전처리)
    df = clean_column_names(df)
    
    # 2. 계산 실행
    result_df = calculate_target_volume(df, target_irr, tax_rate, period)
    
    st.subheader("📊 분석 결과 확인")
    
    # 결과 미리보기 (핵심 컬럼만 자동 선택)
    # 컬럼명이 조금 달라도 키워드로 찾아서 보여줌
    key_cols = ["공사관리번호", "투자분석명", "용도", "연간판매량", "최소경제성만족판매량", "달성률"]
    display_cols = []
    for k in key_cols:
        found = find_col(result_df, k)
        if found:
            display_cols.append(found)
            
    st.dataframe(
        result_df[display_cols].style.background_gradient(subset=[find_col(result_df, "최소경제성만족판매량")], cmap="Oranges"),
        use_container_width=True
    )

    # 3. 다운로드 버튼
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
        worksheet = writer.sheets['Sheet1']
        worksheet.set_column('A:Z', 18)
        
    st.download_button(
        label="📥 분석 결과 엑셀 다운로드 (Click)",
        data=output.getvalue(),
        file_name="최소경제성만족판매량_분석결과.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
